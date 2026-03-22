import boto3
import os
from typing import Optional, List
from botocore.exceptions import ClientError
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class S3Service:
    """Service for interacting with AWS S3"""
    
    def __init__(self):
        self.client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
            endpoint_url=settings.S3_ENDPOINT_URL or None,
        )
        self.bucket_name = settings.S3_BUCKET_NAME
    
    def upload_file(
        self,
        file_path: str,
        s3_key: str,
        content_type: Optional[str] = None,
        extra_args: Optional[dict] = None,
    ) -> str:
        """
        Upload a file to S3
        
        Args:
            file_path: Local path to the file
            s3_key: S3 object key (path in bucket)
            content_type: Optional content type
            extra_args: Additional arguments for upload
            
        Returns:
            S3 URL of the uploaded file
        """
        try:
            upload_args = extra_args or {}
            if content_type:
                upload_args["ContentType"] = content_type
            
            self.client.upload_file(
                file_path,
                self.bucket_name,
                s3_key,
                ExtraArgs=upload_args if upload_args else None,
            )
            
            return self.get_public_url(s3_key)
        except ClientError as e:
            logger.error(f"Failed to upload file to S3: {e}")
            raise
    
    def upload_fileobj(
        self,
        file_obj,
        s3_key: str,
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload a file object to S3
        
        Args:
            file_obj: File-like object
            s3_key: S3 object key
            content_type: Optional content type
            
        Returns:
            S3 URL of the uploaded file
        """
        try:
            extra_args = {}
            if content_type:
                extra_args["ContentType"] = content_type
            
            self.client.upload_fileobj(
                file_obj,
                self.bucket_name,
                s3_key,
                ExtraArgs=extra_args if extra_args else None,
            )
            
            return self.get_public_url(s3_key)
        except ClientError as e:
            logger.error(f"Failed to upload file object to S3: {e}")
            raise
    
    def download_file(self, s3_key: str, local_path: str) -> str:
        """
        Download a file from S3
        
        Args:
            s3_key: S3 object key
            local_path: Local path to save the file
            
        Returns:
            Local path of the downloaded file
        """
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            self.client.download_file(self.bucket_name, s3_key, local_path)
            return local_path
        except ClientError as e:
            logger.error(f"Failed to download file from S3: {e}")
            raise
    
    def delete_file(self, s3_key: str) -> bool:
        """
        Delete a file from S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if successful
        """
        try:
            self.client.delete_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError as e:
            logger.error(f"Failed to delete file from S3: {e}")
            raise
    
    def delete_folder(self, prefix: str) -> bool:
        """
        Delete all objects with a given prefix (folder)
        
        Args:
            prefix: S3 key prefix
            
        Returns:
            True if successful
        """
        try:
            # List all objects with the prefix
            paginator = self.client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)
            
            objects_to_delete = []
            for page in pages:
                if "Contents" in page:
                    for obj in page["Contents"]:
                        objects_to_delete.append({"Key": obj["Key"]})
            
            if objects_to_delete:
                self.client.delete_objects(
                    Bucket=self.bucket_name,
                    Delete={"Objects": objects_to_delete},
                )
            
            return True
        except ClientError as e:
            logger.error(f"Failed to delete folder from S3: {e}")
            raise
    
    def get_public_url(self, s3_key: str) -> str:
        """
        Get the public URL for an S3 object
        
        Args:
            s3_key: S3 object key
            
        Returns:
            Public URL
        """
        if settings.S3_ENDPOINT_URL:
            # For MinIO or LocalStack
            return f"{settings.S3_ENDPOINT_URL}/{self.bucket_name}/{s3_key}"
        return f"https://{self.bucket_name}.s3.{settings.AWS_REGION}.amazonaws.com/{s3_key}"
    
    def generate_presigned_url(
        self,
        s3_key: str,
        expiration: int = 3600,
        http_method: str = "get_object",
    ) -> str:
        """
        Generate a presigned URL for an S3 object
        
        Args:
            s3_key: S3 object key
            expiration: URL expiration time in seconds
            http_method: S3 operation (get_object, put_object)
            
        Returns:
            Presigned URL
        """
        try:
            url = self.client.generate_presigned_url(
                http_method,
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return url
        except ClientError as e:
            logger.error(f"Failed to generate presigned URL: {e}")
            raise
    
    def generate_presigned_upload_url(
        self,
        s3_key: str,
        content_type: str,
        expiration: int = 3600,
    ) -> dict:
        """
        Generate a presigned URL for uploading to S3
        
        Args:
            s3_key: S3 object key
            content_type: Content type of the file
            expiration: URL expiration time in seconds
            
        Returns:
            Dict with upload URL and fields
        """
        try:
            response = self.client.generate_presigned_post(
                self.bucket_name,
                s3_key,
                Fields={"Content-Type": content_type},
                Conditions=[
                    {"Content-Type": content_type},
                    ["content-length-range", 1, settings.MAX_FILE_SIZE],
                ],
                ExpiresIn=expiration,
            )
            return response
        except ClientError as e:
            logger.error(f"Failed to generate presigned upload URL: {e}")
            raise
    
    def list_objects(self, prefix: str) -> List[dict]:
        """
        List objects in S3 with a given prefix
        
        Args:
            prefix: S3 key prefix
            
        Returns:
            List of object metadata
        """
        try:
            paginator = self.client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.bucket_name, Prefix=prefix)
            
            objects = []
            for page in pages:
                if "Contents" in page:
                    objects.extend(page["Contents"])
            
            return objects
        except ClientError as e:
            logger.error(f"Failed to list objects in S3: {e}")
            raise
    
    def file_exists(self, s3_key: str) -> bool:
        """
        Check if a file exists in S3
        
        Args:
            s3_key: S3 object key
            
        Returns:
            True if file exists
        """
        try:
            self.client.head_object(Bucket=self.bucket_name, Key=s3_key)
            return True
        except ClientError:
            return False


# Singleton instance
s3_service = S3Service()
