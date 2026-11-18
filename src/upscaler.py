import io
import math
from pathlib import Path
from typing import Callable

import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as functional
from PIL import Image, UnidentifiedImageError

MAX_IMAGE_PIXELS = 5_000_000
OUTPUT_LONG_EDGE = 3_840
MAX_OUTPUT_BYTES = 20 * 1024 * 1024

class ResidualDenseBlock(nn.Module):
    def __init__(self, features=64, growth=32):
        super().__init__()
        self.conv1 = nn.Conv2d(features, growth, 3, 1, 1)
        self.conv2 = nn.Conv2d(features + growth, growth, 3, 1, 1)
        self.conv3 = nn.Conv2d(features + growth * 2, growth, 3, 1, 1)
        self.conv4 = nn.Conv2d(features + growth * 3, growth, 3, 1, 1)
        self.conv5 = nn.Conv2d(features + growth * 4, features, 3, 1, 1)
        self.activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, value):
        first = self.activation(self.conv1(value))
        second = self.activation(self.conv2(torch.cat((value, first), dim=1)))
        third = self.activation(self.conv3(torch.cat((value, first, second), dim=1)))
        fourth = self.activation(self.conv4(torch.cat((value, first, second, third), dim=1)))
        fifth = self.conv5(torch.cat((value, first, second, third, fourth), dim=1))
        return value + fifth * 0.2


class ResidualInResidualDenseBlock(nn.Module):
    def __init__(self):
        super().__init__()
        self.rdb1 = ResidualDenseBlock()
        self.rdb2 = ResidualDenseBlock()
        self.rdb3 = ResidualDenseBlock()

    def forward(self, value):
        return value + self.rdb3(self.rdb2(self.rdb1(value))) * 0.2


class RRDBNet(nn.Module):
    def __init__(self, blocks=23, scale=2):
        super().__init__()
        self.scale = scale
        features = 64
        input_channels = 12 if scale == 2 else 3
        self.unshuffle = nn.PixelUnshuffle(2) if scale == 2 else nn.Identity()
        self.conv_first = nn.Conv2d(input_channels, features, 3, 1, 1)
        self.body = nn.Sequential(*(ResidualInResidualDenseBlock() for _ in range(blocks)))
        self.conv_body = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_up1 = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_up2 = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_hr = nn.Conv2d(features, features, 3, 1, 1)
        self.conv_last = nn.Conv2d(features, 3, 3, 1, 1)
        self.activation = nn.LeakyReLU(negative_slope=0.2, inplace=True)

    def forward(self, value):
        if self.scale == 2:
            value = self.unshuffle(value)
        features = self.conv_first(value)
        features = features + self.conv_body(self.body(features))
        features = self.activation(
            self.conv_up1(functional.interpolate(features, scale_factor=2, mode="nearest"))
        )
        features = self.activation(
            self.conv_up2(functional.interpolate(features, scale_factor=2, mode="nearest"))
        )
        features = self.activation(self.conv_hr(features))
        return self.conv_last(features)


def decode_image(image_bytes: bytes) -> np.ndarray:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            width, height = source.size
            if width * height > MAX_IMAGE_PIXELS:
                raise ValueError("Ukuran gambar terlalu besar. Batasnya 5 megapiksel.")
            source.verify()
    except UnidentifiedImageError as error:
        raise ValueError("File tidak dapat dibaca sebagai gambar.") from error
    except Image.DecompressionBombError as error:
        raise ValueError("Ukuran gambar terlalu besar. Batasnya 5 megapiksel.") from error
    except OSError as error:
        raise ValueError("File gambar rusak atau tidak didukung.") from error

    image = cv2.imdecode(np.frombuffer(image_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("File tidak dapat dibaca sebagai gambar.")
    return image


class RealESRGANUpscaler:
    scale = 2
    max_pixels = MAX_IMAGE_PIXELS
    output_long_edge = OUTPUT_LONG_EDGE
    tile_size = 128
    tile_padding = 10

    def __init__(self, model_path: Path, scale: int):
        self.scale = scale
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.use_half_precision = self.device.type == "cuda"
        checkpoint = torch.load(model_path, map_location="cpu", weights_only=True)
        weights = checkpoint.get("params_ema", checkpoint.get("params"))
        if weights is None:
            raise ValueError("Checkpoint tidak berisi parameter model Real-ESRGAN.")

        self.model = RRDBNet(scale=scale)
        self.model.load_state_dict(weights, strict=True)
        self.model.eval().to(self.device, memory_format=torch.channels_last)
        if self.use_half_precision:
            self.model.half()

    def enhance(
        self,
        image: np.ndarray,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> bytes:
        height, width = image.shape[:2]
        padded_height = height + height % 2
        padded_width = width + width % 2
        total_tiles = (
            math.ceil(padded_height / self.tile_size)
            * math.ceil(padded_width / self.tile_size)
        )
        completed_tiles = 0
        input_tensor = (
            torch.from_numpy(np.ascontiguousarray(image.transpose(2, 0, 1)))
            .unsqueeze(0)
            .to(
                device=self.device,
                dtype=torch.float16 if self.use_half_precision else torch.float32,
                memory_format=torch.channels_last,
            )
            .div_(255)
        )
        if padded_height != height or padded_width != width:
            input_tensor = functional.pad(
                input_tensor,
                (0, padded_width - width, 0, padded_height - height),
                mode="replicate",
            )
        output = np.empty(
            (padded_height * self.scale, padded_width * self.scale, 3),
            dtype=np.uint8,
        )

        with torch.inference_mode():
            for top in range(0, padded_height, self.tile_size):
                for left in range(0, padded_width, self.tile_size):
                    bottom = min(top + self.tile_size, padded_height)
                    right = min(left + self.tile_size, padded_width)
                    tile_top = max(top - self.tile_padding, 0)
                    tile_left = max(left - self.tile_padding, 0)
                    tile_bottom = min(bottom + self.tile_padding, padded_height)
                    tile_right = min(right + self.tile_padding, padded_width)

                    tile = input_tensor[:, :, tile_top:tile_bottom, tile_left:tile_right]
                    enhanced_tile = self.model(tile).clamp_(0, 1)
                    enhanced_tile = (
                        enhanced_tile.squeeze(0)
                        .permute(1, 2, 0)
                        .mul(255)
                        .round()
                        .to(torch.uint8)
                        .cpu()
                        .numpy()
                    )

                    crop_top = (top - tile_top) * self.scale
                    crop_left = (left - tile_left) * self.scale
                    crop_bottom = crop_top + (bottom - top) * self.scale
                    crop_right = crop_left + (right - left) * self.scale
                    output[
                        top * self.scale:bottom * self.scale,
                        left * self.scale:right * self.scale,
                    ] = enhanced_tile[crop_top:crop_bottom, crop_left:crop_right]
                    completed_tiles += 1
                    if on_progress is not None:
                        on_progress(completed_tiles, total_tiles)

        output = output[:height * self.scale, :width * self.scale]
        output_height, output_width = output.shape[:2]
        if max(output_height, output_width) != self.output_long_edge:
            resize_factor = self.output_long_edge / max(output_height, output_width)
            target_size = (
                max(1, round(output_width * resize_factor)),
                max(1, round(output_height * resize_factor)),
            )
            interpolation = (
                cv2.INTER_CUBIC
                if resize_factor > 1
                else cv2.INTER_AREA
            )
            output = cv2.resize(output, target_size, interpolation=interpolation)

        def encode_jpeg(quality):
            buffer = io.BytesIO()
            Image.fromarray(cv2.cvtColor(output, cv2.COLOR_BGR2RGB)).save(
                buffer,
                format="JPEG",
                quality=quality,
                subsampling=0,
                optimize=False,
                progressive=False,
            )
            return buffer.getvalue()

        encoded = encode_jpeg(100)
        if len(encoded) <= MAX_OUTPUT_BYTES:
            return encoded

        lowest_quality = 1
        highest_quality = 99
        best_encoded = None
        while lowest_quality <= highest_quality:
            quality = (lowest_quality + highest_quality) // 2
            candidate = encode_jpeg(quality)
            if len(candidate) <= MAX_OUTPUT_BYTES:
                best_encoded = candidate
                lowest_quality = quality + 1
            else:
                highest_quality = quality - 1

        if best_encoded is None:
            raise RuntimeError("Ukuran hasil gambar tidak dapat dibatasi hingga 20 MB.")
        return best_encoded
