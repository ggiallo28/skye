"""Multimodal input handling for images, audio, and video.

This module provides utilities for processing multimodal inputs (images, audio, video)
and converting them to provider-specific formats.

**ARCHITECTURAL DEBT:**
This module contains provider-specific transformation methods (to_openai_format,
to_anthropic_format, to_bedrock_format) that violate the provider encapsulation
principle. In a future refactor, these methods should be moved to the respective
provider classes as part of their _transform_messages() implementation.

For now, this is acceptable as multimodal handling is a specialized concern, but
the long-term goal is to have all provider-specific logic within provider classes.
"""

import base64
from pathlib import Path
from typing import Union, Dict, Any

from skye.base.exceptions import UnsupportedModalityError, ValidationError
from skye.base.messages import sniff_image_mime


class ImageHandler:
    """Handle image inputs for multimodal models.
    
    Supports multiple input formats:
    - URLs (http://, https://)
    - Data URIs (data:image/...)
    - File paths (Path or str)
    - Raw bytes
    
    Provides conversion to provider-specific formats:
    - OpenAI format
    - Anthropic format
    - Bedrock format
    """
    
    @staticmethod
    def process_image(image_input: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Process image input into provider-compatible format.
        
        Args:
            image_input: URL, file path, base64 string, or raw bytes
        
        Returns:
            Dict with image data in appropriate format
        
        Raises:
            ValidationError: If image input is invalid or file not found
        
        Example:
            >>> # URL input
            >>> ImageHandler.process_image("https://example.com/image.jpg")
            {'type': 'image_url', 'image_url': {'url': 'https://example.com/image.jpg'}}
            
            >>> # File path input
            >>> ImageHandler.process_image(Path("image.png"))
            {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,...'}}
        """
        if isinstance(image_input, str):
            if image_input.startswith("http://") or image_input.startswith("https://"):
                return {"type": "image_url", "image_url": {"url": image_input}}
            elif image_input.startswith("data:image"):
                return {"type": "image_url", "image_url": {"url": image_input}}
            else:
                # Assume file path
                return ImageHandler.process_image(Path(image_input))
        
        elif isinstance(image_input, Path):
            if not image_input.exists():
                raise ValidationError(
                    f"Image file not found: {image_input}",
                    "image_input",
                    str(image_input)
                )
            
            with open(image_input, "rb") as f:
                image_bytes = f.read()
            
            # Detect mime type from extension
            mime_type = ImageHandler._get_mime_type(image_input.suffix)
            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
            }
        
        elif isinstance(image_input, bytes):
            base64_image = base64.b64encode(image_input).decode("utf-8")
            mime_type = ImageHandler._sniff_mime_type(image_input)
            return {
                "type": "image_url",
                "image_url": {"url": f"data:{mime_type};base64,{base64_image}"}
            }
        
        else:
            raise ValidationError(
                f"Invalid image input type: {type(image_input)}",
                "image_input",
                str(image_input)
            )
    
    @staticmethod
    def _sniff_mime_type(data: bytes) -> str:
        """MIME type of raw image bytes from their first bytes (JPEG when unknown)."""
        return sniff_image_mime(data)

    @staticmethod
    def _get_mime_type(extension: str) -> str:
        """Get MIME type from file extension.
        
        Args:
            extension: File extension (e.g., '.jpg', '.png')
        
        Returns:
            MIME type string (e.g., 'image/jpeg')
        """
        mime_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".gif": "image/gif",
            ".webp": "image/webp"
        }
        return mime_types.get(extension.lower(), "image/jpeg")
    
    @staticmethod
    def to_openai_format(image_input: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Convert image to OpenAI format.
        
        OpenAI expects images in the format:
        {
            "type": "image_url",
            "image_url": {"url": "<url or data uri>"}
        }
        
        Args:
            image_input: URL, file path, or raw bytes
        
        Returns:
            Dict in OpenAI format
        
        Example:
            >>> ImageHandler.to_openai_format("https://example.com/image.jpg")
            {'type': 'image_url', 'image_url': {'url': 'https://example.com/image.jpg'}}
        """
        return ImageHandler.process_image(image_input)
    
    @staticmethod
    def to_anthropic_format(image_input: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Convert image to Anthropic format.
        
        Anthropic expects images in the format:
        {
            "type": "image",
            "source": {
                "type": "base64" or "url",
                "media_type": "image/jpeg",
                "data": "<base64>" or "url": "<url>"
            }
        }
        
        Args:
            image_input: URL, file path, or raw bytes
        
        Returns:
            Dict in Anthropic format
        
        Example:
            >>> ImageHandler.to_anthropic_format("https://example.com/image.jpg")
            {'type': 'image', 'source': {'type': 'url', 'url': 'https://example.com/image.jpg'}}
        """
        processed = ImageHandler.process_image(image_input)
        if processed["type"] == "image_url":
            url = processed["image_url"]["url"]
            if url.startswith("data:"):
                # Extract base64 data
                parts = url.split(",", 1)
                media_type = parts[0].split(";")[0].split(":")[1]
                data = parts[1]
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": data
                    }
                }
            else:
                return {
                    "type": "image",
                    "source": {
                        "type": "url",
                        "url": url
                    }
                }
        return processed
    
    @staticmethod
    def to_bedrock_format(image_input: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Convert image to Bedrock format.
        
        Bedrock expects images in the format:
        {
            "image": {
                "format": "jpeg" or "png",
                "source": {"bytes": <bytes>}
            }
        }
        
        Args:
            image_input: URL, file path, or raw bytes
        
        Returns:
            Dict in Bedrock format

        Raises:
            UnsupportedModalityError: If the image is a URL, which Bedrock does not fetch.
            ValidationError: If the image input is invalid.
        
        Example:
            >>> ImageHandler.to_bedrock_format(Path("image.png"))
            {'image': {'format': 'png', 'source': {'bytes': b'...'}}}
        """
        processed = ImageHandler.process_image(image_input)
        if processed["type"] == "image_url":
            url = processed["image_url"]["url"]
            if url.startswith("data:"):
                parts = url.split(",", 1)
                media_type = parts[0].split(";")[0].split(":")[1]
                data = parts[1]
                return {
                    "image": {
                        "format": media_type.split("/")[1],
                        "source": {"bytes": base64.b64decode(data)}
                    }
                }
            raise UnsupportedModalityError(
                "Bedrock does not support the image modality given as a URL (it does not fetch URLs): "
                "pass a file path, bytes or a data URI",
                provider="bedrock",
                modality="image",
            )
        return processed

    @staticmethod
    def to_google_format(image_input: Union[str, Path, bytes]) -> Dict[str, Any]:
        """Convert image to Google (Gemini) part format.

        Inline data becomes ``{"inlineData": {"mimeType": ..., "data": <base64>}}``;
        a URL becomes ``{"fileData": {"fileUri": ...}}``.
        """
        processed = ImageHandler.process_image(image_input)
        url = processed["image_url"]["url"]
        if url.startswith("data:"):
            head, data = url.split(",", 1)
            return {"inlineData": {"mimeType": head.split(";")[0].split(":")[1], "data": data}}
        return {"fileData": {"fileUri": url}}
