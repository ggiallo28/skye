"""Unit tests for ImageHandler utility."""

import base64
from pathlib import Path

import pytest

from skye.base.exceptions import ValidationError
from skye.models.utilities.multimodal import ImageHandler


class TestImageHandler:
    """Test ImageHandler utility."""
    
    def test_process_image_with_http_url(self):
        """Test processing HTTP URL."""
        url = "http://example.com/image.jpg"
        result = ImageHandler.process_image(url)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == url
    
    def test_process_image_with_https_url(self):
        """Test processing HTTPS URL."""
        url = "https://example.com/image.png"
        result = ImageHandler.process_image(url)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == url
    
    def test_process_image_with_data_uri(self):
        """Test processing data URI."""
        data_uri = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
        result = ImageHandler.process_image(data_uri)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == data_uri
    
    def test_process_image_with_file_path_string(self):
        """Test processing file path as string."""
        path = "tests/fixtures/images/test_image.png"
        result = ImageHandler.process_image(path)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith("data:image/png;base64,")
    
    def test_process_image_with_path_object(self):
        """Test processing Path object."""
        path = Path("tests/fixtures/images/test_image.jpg")
        result = ImageHandler.process_image(path)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith("data:image/jpeg;base64,")
    
    def test_process_image_with_bytes(self):
        """Test processing raw bytes."""
        image_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        result = ImageHandler.process_image(image_bytes)
        
        assert result["type"] == "image_url"
        # The type is read from the bytes (PNG signature); unknown bytes are sent as JPEG
        assert result["image_url"]["url"].startswith("data:image/png;base64,")
        assert ImageHandler.process_image(b"\x00\x01")["image_url"]["url"].startswith("data:image/jpeg;base64,")
        
        # Verify base64 encoding
        base64_part = result["image_url"]["url"].split(",")[1]
        decoded = base64.b64decode(base64_part)
        assert decoded == image_bytes
    
    def test_process_image_with_nonexistent_file(self):
        """Test processing nonexistent file raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageHandler.process_image(Path("nonexistent.png"))
        
        assert "not found" in str(exc_info.value).lower()
    
    def test_process_image_with_invalid_type(self):
        """Test processing invalid type raises error."""
        with pytest.raises(ValidationError) as exc_info:
            ImageHandler.process_image(123)  # type: ignore
        
        assert "invalid image input type" in str(exc_info.value).lower()
    
    @pytest.mark.parametrize("extension,expected_mime", [
        (".jpg", "image/jpeg"),
        (".jpeg", "image/jpeg"),
        (".png", "image/png"),
        (".gif", "image/gif"),
        (".webp", "image/webp"),
        (".JPG", "image/jpeg"),  # Test case insensitivity
        (".PNG", "image/png"),
        (".unknown", "image/jpeg"),  # Default fallback
    ])
    def test_get_mime_type(self, extension, expected_mime):
        """Test MIME type detection from extension."""
        mime_type = ImageHandler._get_mime_type(extension)
        assert mime_type == expected_mime
    
    def test_to_openai_format_with_url(self):
        """Test OpenAI format conversion with URL."""
        url = "https://example.com/image.jpg"
        result = ImageHandler.to_openai_format(url)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"] == url
    
    def test_to_openai_format_with_file(self):
        """Test OpenAI format conversion with file."""
        path = Path("tests/fixtures/images/test_image.png")
        result = ImageHandler.to_openai_format(path)
        
        assert result["type"] == "image_url"
        assert result["image_url"]["url"].startswith("data:image/png;base64,")
    
    def test_to_anthropic_format_with_url(self):
        """Test Anthropic format conversion with URL."""
        url = "https://example.com/image.jpg"
        result = ImageHandler.to_anthropic_format(url)
        
        assert result["type"] == "image"
        assert result["source"]["type"] == "url"
        assert result["source"]["url"] == url
    
    def test_to_anthropic_format_with_file(self):
        """Test Anthropic format conversion with file."""
        path = Path("tests/fixtures/images/test_image.png")
        result = ImageHandler.to_anthropic_format(path)
        
        assert result["type"] == "image"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "image/png"
        assert "data" in result["source"]
        
        # Verify base64 data is valid
        base64.b64decode(result["source"]["data"])
    
    def test_to_anthropic_format_with_data_uri(self):
        """Test Anthropic format conversion with data URI."""
        data_uri = "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD"
        result = ImageHandler.to_anthropic_format(data_uri)
        
        assert result["type"] == "image"
        assert result["source"]["type"] == "base64"
        assert result["source"]["media_type"] == "image/jpeg"
        assert result["source"]["data"] == "/9j/4AAQSkZJRgABAQAAAQABAAD"
    
    def test_to_bedrock_format_with_file(self):
        """Test Bedrock format conversion with file."""
        path = Path("tests/fixtures/images/test_image.png")
        result = ImageHandler.to_bedrock_format(path)
        
        assert "image" in result
        assert result["image"]["format"] == "png"
        assert "source" in result["image"]
        assert "bytes" in result["image"]["source"]
        assert isinstance(result["image"]["source"]["bytes"], bytes)
    
    def test_to_bedrock_format_with_jpeg(self):
        """Test Bedrock format conversion with JPEG."""
        path = Path("tests/fixtures/images/test_image.jpg")
        result = ImageHandler.to_bedrock_format(path)
        
        assert result["image"]["format"] == "jpeg"
        assert isinstance(result["image"]["source"]["bytes"], bytes)
    
    def test_to_bedrock_format_with_data_uri(self):
        """Test Bedrock format conversion with data URI."""
        # Read actual image file and create data URI
        path = Path("tests/fixtures/images/test_image.png")
        with open(path, "rb") as f:
            image_bytes = f.read()
        
        base64_data = base64.b64encode(image_bytes).decode("utf-8")
        data_uri = f"data:image/png;base64,{base64_data}"
        
        result = ImageHandler.to_bedrock_format(data_uri)
        
        assert result["image"]["format"] == "png"
        assert result["image"]["source"]["bytes"] == image_bytes
    
    def test_format_conversions_consistency(self):
        """Test that all format conversions work with same input."""
        path = Path("tests/fixtures/images/test_image.jpg")
        
        # All conversions should succeed
        openai_result = ImageHandler.to_openai_format(path)
        anthropic_result = ImageHandler.to_anthropic_format(path)
        bedrock_result = ImageHandler.to_bedrock_format(path)
        
        assert openai_result is not None
        assert anthropic_result is not None
        assert bedrock_result is not None
    
    def test_bytes_input_all_formats(self):
        """Test bytes input works for all format conversions."""
        image_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        
        openai_result = ImageHandler.to_openai_format(image_bytes)
        anthropic_result = ImageHandler.to_anthropic_format(image_bytes)
        bedrock_result = ImageHandler.to_bedrock_format(image_bytes)
        
        assert openai_result["type"] == "image_url"
        assert anthropic_result["type"] == "image"
        assert "image" in bedrock_result
