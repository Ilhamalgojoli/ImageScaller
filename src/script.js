const fileInput = document.querySelector("#image-input");
const dropzone = document.querySelector("#dropzone");
const imageList = document.querySelector("#image-list");
const imageListWrap = document.querySelector("#image-list-wrap");
const sourceCount = document.querySelector("#source-count");
const uploadMessage = document.querySelector("#upload-message");
const clearImagesButton = document.querySelector("#clear-images");
const upscaleButton = document.querySelector("#upscale-button");
const scaleSelect = document.querySelector("#scale-select");
const resultList = document.querySelector("#result-list");
const resultEmpty = document.querySelector("#result-empty");
const processingMessage = document.querySelector("#processing-message");
const selectedImages = [];
let dragDepth = 0;
let isProcessing = false;

function formatFileSize(bytes) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderImages() {
  imageList.replaceChildren();
  imageListWrap.hidden = selectedImages.length === 0;
  upscaleButton.hidden = selectedImages.length === 0;
  upscaleButton.disabled = isProcessing;
  scaleSelect.disabled = isProcessing;
  if (!isProcessing) {
    upscaleButton.textContent = `Upscale x${scaleSelect.value}`;
  }
  sourceCount.textContent = `${selectedImages.length} gambar`;

  selectedImages.forEach((image, index) => {
    const item = document.createElement("li");
    item.className = "flex min-w-0 items-center gap-2.5 rounded-[10px] border border-[#eef0f5] bg-white p-[7px]";

    const thumbnail = document.createElement("img");
    thumbnail.className = "size-[38px] flex-none rounded-[7px] bg-[#f2f3f8] object-cover";
    thumbnail.src = image.url;
    thumbnail.alt = "";

    const details = document.createElement("span");
    details.className = "grid min-w-0 flex-1 gap-[3px]";

    const name = document.createElement("span");
    name.className = "overflow-hidden text-ellipsis whitespace-nowrap text-[10px] font-semibold text-[#3e4961]";
    name.textContent = image.file.name;
    name.title = image.file.name;

    const size = document.createElement("span");
    size.className = "text-[9px] text-[#969eb0]";
    size.textContent = formatFileSize(image.file.size);

    const removeButton = document.createElement("button");
    removeButton.className = "grid size-[27px] flex-none place-items-center rounded-[7px] text-lg leading-none text-[#9299ab] hover:bg-[#fff0f1] hover:text-[#d65b65]";
    removeButton.type = "button";
    removeButton.setAttribute("aria-label", `Hapus ${image.file.name}`);
    removeButton.textContent = "×";
    removeButton.addEventListener("click", () => removeImage(index));

    details.append(name, size);
    item.append(thumbnail, details, removeButton);
    imageList.append(item);
  });
}

function renderResults() {
  resultList.replaceChildren();
  const imagesWithResults = selectedImages.filter(
    (image) => image.processing || image.resultUrl || image.error
  );
  resultEmpty.hidden = imagesWithResults.length > 0;

  imagesWithResults.forEach((image) => {
    const item = document.createElement("li");
    item.className = "overflow-hidden rounded-xl border border-[#e8ebf3] bg-white";

    if (image.resultUrl) {
      const preview = document.createElement("img");
      preview.className = "max-h-72 w-full bg-[#f7f8fc] object-contain";
      preview.src = image.resultUrl;
      preview.alt = `Hasil upscaling ${image.file.name}`;
      item.append(preview);
    }

    const details = document.createElement("div");
    details.className = "flex flex-wrap items-center justify-between gap-2 p-3";

    const name = document.createElement("span");
    name.className = "min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap text-[11px] font-semibold text-[#3e4961]";
    name.textContent = image.file.name;
    name.title = image.file.name;

    const status = document.createElement("span");
    status.className = image.error
      ? "w-full break-all text-[10px] text-[#bb4f58]"
      : "w-full break-all text-[10px] text-[#78829a]";
    status.textContent = image.error || (
      image.processing
        ? "Sedang diperbesar..."
        : image.outputPath
          ? `${image.outputResolution} · JPEG ${formatFileSize(image.outputSize)} · tersimpan di: ${image.outputPath}`
          : `Selesai x${image.scale} · ${image.outputResolution} · JPEG kualitas tinggi · batas 20 MB`
    );
    details.append(name, status);

    item.append(details);
    resultList.append(item);
  });
}

function addImages(files) {
  const incomingFiles = Array.from(files);
  const imageFiles = incomingFiles.filter((file) => file.type.startsWith("image/"));
  const rejectedCount = incomingFiles.length - imageFiles.length;

  imageFiles.forEach((file) => {
    const duplicate = selectedImages.some((image) =>
      image.file.name === file.name &&
      image.file.size === file.size &&
      image.file.lastModified === file.lastModified
    );

    if (!duplicate) {
      selectedImages.push({ file, url: URL.createObjectURL(file) });
    }
  });

  if (rejectedCount > 0) {
    uploadMessage.textContent = `${rejectedCount} file dilewati karena bukan gambar.`;
  } else if (imageFiles.length > 0) {
    uploadMessage.textContent = "";
  }

  renderImages();
}

function removeImage(index) {
  const [image] = selectedImages.splice(index, 1);
  URL.revokeObjectURL(image.url);
  if (image.resultUrl) {
    URL.revokeObjectURL(image.resultUrl);
  }
  renderImages();
  renderResults();
}

function clearImages() {
  selectedImages.forEach((image) => {
    URL.revokeObjectURL(image.url);
    if (image.resultUrl) {
      URL.revokeObjectURL(image.resultUrl);
    }
  });
  selectedImages.length = 0;
  uploadMessage.textContent = "";
  renderImages();
  renderResults();
  processingMessage.hidden = true;
}

async function upscaleImages() {
  if (isProcessing || selectedImages.length === 0) {
    return;
  }

  isProcessing = true;
  upscaleButton.disabled = true;
  upscaleButton.textContent = "Sedang memproses...";
  scaleSelect.disabled = true;
  const scale = Number(scaleSelect.value);
  processingMessage.hidden = false;
  const queue = [...selectedImages];
  let completed = 0;
  let failed = 0;

  for (let index = 0; index < queue.length; index += 1) {
    const image = queue[index];
    if (!selectedImages.includes(image)) {
      continue;
    }

    processingMessage.textContent = `Memproses gambar ${index + 1} dari ${queue.length}...`;
    image.processing = true;
    image.error = "";
    if (image.resultUrl) {
      URL.revokeObjectURL(image.resultUrl);
      image.resultUrl = "";
    }
    renderResults();

    try {
      const formData = new FormData();
      formData.append("image", image.file);
      formData.append("scale", String(scale));
      const progressId = crypto.randomUUID();
      let response;
      let requestError;
      let requestFinished = false;
      fetch("/api/upscale", {
        method: "POST",
        headers: { "X-Progress-Id": progressId },
        body: formData,
      })
        .then((result) => {
          response = result;
        })
        .catch((error) => {
          requestError = error;
        })
        .finally(() => {
          requestFinished = true;
        });

      while (!requestFinished) {
        const progressResponse = await fetch(`/api/upscale/progress/${progressId}`);
        if (progressResponse.ok) {
          const progress = await progressResponse.json();
          if (progress.stage === "waiting") {
            processingMessage.textContent = "Menunggu proses gambar sebelumnya...";
          } else if (progress.stage === "loading_model") {
            processingMessage.textContent = "Menyiapkan model Real-ESRGAN...";
          } else if (progress.total_tiles > 0) {
            const percentage = Math.round(
              (progress.completed_tiles / progress.total_tiles) * 100
            );
            processingMessage.textContent =
              `Memproses gambar ${index + 1} dari ${queue.length} · ` +
              `tile ${progress.completed_tiles}/${progress.total_tiles} (${percentage}%)`;
          } else {
            processingMessage.textContent = `Memproses gambar ${index + 1} dari ${queue.length}...`;
          }
        } else if (progressResponse.status !== 404) {
          const payload = await progressResponse.json().catch(() => null);
          throw new Error(payload?.error || "Tidak dapat membaca progres upscaling.");
        }

        if (!requestFinished) {
          await new Promise((resolve) => setTimeout(resolve, 500));
        }
      }

      if (requestError) {
        throw requestError;
      }

      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(payload?.error || "Upscaling gagal. Coba lagi.");
      }

      const resultUrl = URL.createObjectURL(await response.blob());
      const outputPath = response.headers.get("X-Output-Path");
      const outputSize = Number(response.headers.get("X-Output-Size"));
      const outputResolution = response.headers.get("X-Output-Resolution");
      if (!outputPath || !outputResolution || !Number.isSafeInteger(outputSize) || outputSize <= 0) {
        URL.revokeObjectURL(resultUrl);
        throw new Error("Hasil dibuat, tetapi informasi file tersimpan tidak diterima.");
      }
      if (!selectedImages.includes(image)) {
        URL.revokeObjectURL(resultUrl);
        continue;
      }

      image.resultUrl = resultUrl;
      image.outputPath = outputPath;
      image.outputSize = outputSize;
      image.outputResolution = outputResolution;
      image.scale = scale;
      completed += 1;
    } catch (error) {
      image.error = error instanceof Error ? error.message : "Upscaling gagal. Coba lagi.";
      failed += 1;
    } finally {
      image.processing = false;
      renderResults();
    }
  }

  isProcessing = false;
  renderImages();
  processingMessage.textContent = failed > 0
    ? `Selesai: ${completed} berhasil, ${failed} gagal.`
    : `Selesai: ${completed} gambar berhasil diperbesar.`;
}

fileInput.addEventListener("change", (event) => {
  addImages(event.target.files);
  fileInput.value = "";
});

clearImagesButton.addEventListener("click", clearImages);
upscaleButton.addEventListener("click", upscaleImages);
scaleSelect.addEventListener("change", renderImages);

dropzone.addEventListener("keydown", (event) => {
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    fileInput.click();
  }
});

dropzone.addEventListener("dragenter", (event) => {
  event.preventDefault();
  dragDepth += 1;
  dropzone.classList.add("border-[#8178f0]", "bg-[#f5f4ff]", "scale-[1.012]");
});

dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
});

dropzone.addEventListener("dragleave", (event) => {
  event.preventDefault();
  dragDepth -= 1;
  if (dragDepth <= 0) {
    dragDepth = 0;
    dropzone.classList.remove("border-[#8178f0]", "bg-[#f5f4ff]", "scale-[1.012]");
  }
});

dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dragDepth = 0;
  dropzone.classList.remove("border-[#8178f0]", "bg-[#f5f4ff]", "scale-[1.012]");
  addImages(event.dataTransfer.files);
});

window.addEventListener("beforeunload", () => {
  selectedImages.forEach((image) => {
    URL.revokeObjectURL(image.url);
    if (image.resultUrl) {
      URL.revokeObjectURL(image.resultUrl);
    }
  });
});
