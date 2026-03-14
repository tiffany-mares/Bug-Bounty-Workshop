import json
import os

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import EmptyPage, PageNotAnInteger, Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render

from .batch import process_batch
from .forms import BatchUploadForm, PresetForm, PresetImportForm, UploadForm
from .halftone import apply_halftone
from .models import BatchJob, ImageUpload, Preset
from .utils import validate_preset_config


@login_required
def upload_view(request):
    if request.method == "POST":
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            upload = ImageUpload(user=request.user, original=request.FILES["image"])
            upload.save()

            original_path = upload.original.path
            filename = f"halftone_{upload.pk}.png"
            output_path = os.path.join(settings.MEDIA_ROOT, "processed", filename)
            os.makedirs(os.path.dirname(output_path), exist_ok=True)

            # Use user's profile preferences if available
            dot_spacing = 10
            style = "classic"
            try:
                profile = request.user.profile
                dot_spacing = profile.dot_spacing
                style = profile.style
            except Exception:
                pass

            apply_halftone(original_path, output_path, dot_spacing=dot_spacing, style=style)

            upload.processed = f"processed/{filename}"
            upload.save()

            return redirect("result", pk=upload.pk)
    else:
        form = UploadForm()
    return render(request, "processor/upload.html", {"form": form})


@login_required
def result_view(request, pk):
    upload = get_object_or_404(ImageUpload, pk=pk, user=request.user)
    return render(request, "processor/result.html", {"upload": upload})


@login_required
def gallery_view(request):
    uploads = ImageUpload.objects.filter(user=request.user).order_by("-uploaded_at")

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        # AJAX infinite scroll — cursor-based pagination
        after_id = request.GET.get("after")
        per_page = 12
        if after_id:
            uploads = uploads.filter(pk__lt=int(after_id)).order_by("-pk")[:per_page]
        else:
            uploads = uploads.order_by("-pk")[:per_page]

        data = [
            {
                "id": u.pk,
                "title": u.title,
                "url": u.processed.url if u.processed else None,
            }
            for u in uploads
        ]
        return JsonResponse({"results": data, "has_more": len(data) == per_page})

    # Normal path — standard page-based pagination
    paginator = Paginator(uploads, 12)
    page = request.GET.get("page", 1)
    try:
        page_obj = paginator.page(page)
    except (PageNotAnInteger, EmptyPage):
        page_obj = paginator.page(1)

    return render(request, "processor/gallery.html", {"page_obj": page_obj})


def shared_view(request, token):
    upload = get_object_or_404(ImageUpload, share_token=token, is_public=True)
    upload.view_count += 1
    upload.save()
    return render(request, "processor/shared.html", {"upload": upload})


@login_required
def preset_list_view(request):
    presets = Preset.objects.filter(user=request.user).order_by("-created_at")
    return render(request, "processor/presets.html", {"presets": presets})


@login_required
def preset_create_view(request):
    if request.method == "POST":
        form = PresetForm(request.POST)
        if form.is_valid():
            config = {
                "dot_spacing": form.cleaned_data["dot_spacing"],
                "style": form.cleaned_data["style"],
            }
            try:
                validate_preset_config(config)
            except ValidationError as e:
                form.add_error(None, e.message)
                return render(request, "processor/preset_create.html", {"form": form})
            Preset.objects.create(
                user=request.user,
                name=form.cleaned_data["name"],
                config=config,
                is_default=form.cleaned_data.get("is_default", False),
            )
            return redirect("preset_list")
    else:
        form = PresetForm()
    return render(request, "processor/preset_create.html", {"form": form})


@login_required
def preset_import_view(request):
    if request.method == "POST":
        form = PresetImportForm(request.POST)
        if form.is_valid():
            try:
                data = json.loads(form.cleaned_data["json_data"])
                config = {"dot_spacing": data.get("dot_spacing"), "style": data.get("style")}
                validate_preset_config(config)
                Preset.objects.create(
                    user=request.user,
                    name=data.get("name", "Imported Preset"),
                    config=config,
                )
                return redirect("preset_list")
            except (json.JSONDecodeError, ValidationError) as e:
                form.add_error("json_data", str(e))
    else:
        form = PresetImportForm()
    return render(request, "processor/preset_import.html", {"form": form})


@login_required
def batch_upload_view(request):
    if request.method == "POST":
        form = BatchUploadForm(request.POST, request.FILES)
        if form.is_valid():
            files = request.FILES.getlist("images")
            make_public = form.cleaned_data.get("make_public", False)

            batch = BatchJob.objects.create(
                user=request.user,
                total_images=len(files),
                status="pending",
            )

            for f in files:
                try:
                    upload = ImageUpload(
                        user=request.user,
                        original=f,
                        batch=batch,
                        title=f.name,
                        is_public=make_public,
                    )
                    upload.save()
                except Exception:
                    continue  # Skip invalid files silently

            process_batch(batch.pk)
            return redirect("batch_status", batch_id=batch.pk)
    else:
        form = BatchUploadForm()
    return render(request, "processor/batch_upload.html", {"form": form})


@login_required
def batch_status_view(request, batch_id):
    batch = get_object_or_404(BatchJob, pk=batch_id, user=request.user)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse(
            {
                "status": batch.status,
                "progress": round(batch.processed_count / batch.total_images * 100)
                if batch.total_images > 0
                else 0,
                "completed": batch.processed_count == batch.total_images,
            }
        )

    images = ImageUpload.objects.filter(batch=batch)
    return render(
        request,
        "processor/batch_status.html",
        {"batch": batch, "images": images},
    )
