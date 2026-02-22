import os
import subprocess
import shutil
import json
from typing import List, Dict, Optional
from dataclasses import dataclass
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


@dataclass
class VideoProfile:
    """HLS encoding profile"""
    name: str
    width: int
    height: int
    video_bitrate: str
    audio_bitrate: str


@dataclass
class HLSResult:
    """Result of HLS conversion"""
    master_playlist_path: str
    variant_playlists: List[str]
    segments: List[str]
    output_dir: str


class HLSConverter:
    """Service for converting video files to HLS format with multi-bitrate"""
    
    def __init__(self):
        self.temp_dir = settings.TEMP_DIR
        self.segment_duration = settings.HLS_SEGMENT_DURATION
        self.profiles = [
            VideoProfile(**profile) for profile in settings.HLS_PROFILES
        ]
    
    def get_video_info(self, video_path: str) -> Dict:
        """
        Get video information using ffprobe
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Dictionary with video information
        """
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise Exception(f"ffprobe failed: {result.stderr}")
        
        return json.loads(result.stdout)
    
    def get_video_resolution(self, video_path: str) -> tuple:
        """
        Get video resolution
        
        Args:
            video_path: Path to the video file
            
        Returns:
            Tuple of (width, height)
        """
        info = self.get_video_info(video_path)
        
        for stream in info.get("streams", []):
            if stream.get("codec_type") == "video":
                return stream.get("width", 0), stream.get("height", 0)
        
        return 0, 0
    
    def filter_profiles_by_resolution(
        self,
        video_path: str,
        profiles: Optional[List[VideoProfile]] = None,
    ) -> List[VideoProfile]:
        """
        Filter profiles to only include those that don't exceed source resolution
        
        Args:
            video_path: Path to the video file
            profiles: List of profiles (uses default if None)
            
        Returns:
            Filtered list of profiles
        """
        profiles = profiles or self.profiles
        source_width, source_height = self.get_video_resolution(video_path)
        
        if source_width == 0 or source_height == 0:
            logger.warning("Could not determine video resolution, using all profiles")
            return profiles
        
        filtered = [
            profile for profile in profiles
            if profile.height <= source_height
        ]
        
        # Always include at least one profile
        if not filtered:
            # Use the smallest profile
            filtered = [min(profiles, key=lambda p: p.height)]
        
        return filtered
    
    def convert_to_hls(
        self,
        video_path: str,
        output_dir: str,
        job_id: str,
        profiles: Optional[List[VideoProfile]] = None,
    ) -> HLSResult:
        """
        Convert video to HLS with multiple bitrates
        
        Args:
            video_path: Path to the source video
            output_dir: Directory to save HLS output
            job_id: Unique job identifier
            profiles: List of encoding profiles
            
        Returns:
            HLSResult with paths to generated files
        """
        os.makedirs(output_dir, exist_ok=True)
        
        # Filter profiles based on source resolution
        profiles = self.filter_profiles_by_resolution(video_path, profiles)
        
        logger.info(f"Converting video with {len(profiles)} profiles: {[p.name for p in profiles]}")
        
        variant_playlists = []
        all_segments = []
        
        # Generate each quality variant
        for profile in profiles:
            variant_dir = os.path.join(output_dir, profile.name)
            os.makedirs(variant_dir, exist_ok=True)
            
            playlist_path = os.path.join(variant_dir, "playlist.m3u8")
            segment_pattern = os.path.join(variant_dir, "segment_%03d.ts")
            
            # Build FFmpeg command for this variant
            cmd = self._build_ffmpeg_command(
                video_path,
                playlist_path,
                segment_pattern,
                profile,
            )
            
            logger.info(f"Running FFmpeg for {profile.name}: {' '.join(cmd)}")
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"FFmpeg error for {profile.name}: {result.stderr}")
                raise Exception(f"FFmpeg conversion failed for {profile.name}: {result.stderr}")
            
            variant_playlists.append(playlist_path)
            
            # Collect segment files
            for f in os.listdir(variant_dir):
                if f.endswith(".ts"):
                    all_segments.append(os.path.join(variant_dir, f))
        
        # Generate master playlist
        master_playlist_path = os.path.join(output_dir, "master.m3u8")
        self._generate_master_playlist(master_playlist_path, profiles)
        
        return HLSResult(
            master_playlist_path=master_playlist_path,
            variant_playlists=variant_playlists,
            segments=all_segments,
            output_dir=output_dir,
        )
    
    def _build_ffmpeg_command(
        self,
        input_path: str,
        playlist_path: str,
        segment_pattern: str,
        profile: VideoProfile,
    ) -> List[str]:
        """
        Build FFmpeg command for HLS conversion
        
        Args:
            input_path: Path to source video
            playlist_path: Path for output playlist
            segment_pattern: Pattern for segment files
            profile: Encoding profile
            
        Returns:
            FFmpeg command as list of strings
        """
        return [
            "ffmpeg",
            "-i", input_path,
            "-y",  # Overwrite output files
            "-c:v", "libx264",
            "-c:a", "aac",
            "-b:v", profile.video_bitrate,
            "-b:a", profile.audio_bitrate,
            "-vf", f"scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease,pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2",
            "-preset", "fast",
            "-profile:v", "main",
            "-level", "3.1",
            "-start_number", "0",
            "-hls_time", str(self.segment_duration),
            "-hls_list_size", "0",
            "-hls_segment_filename", segment_pattern,
            "-f", "hls",
            playlist_path,
        ]
    
    def _generate_master_playlist(
        self,
        output_path: str,
        profiles: List[VideoProfile],
    ) -> None:
        """
        Generate master HLS playlist
        
        Args:
            output_path: Path for master playlist
            profiles: List of encoding profiles used
        """
        lines = ["#EXTM3U", "#EXT-X-VERSION:3"]
        
        for profile in profiles:
            # Calculate bandwidth (video + audio in bits per second)
            video_bps = self._parse_bitrate(profile.video_bitrate)
            audio_bps = self._parse_bitrate(profile.audio_bitrate)
            bandwidth = video_bps + audio_bps
            
            lines.append(
                f"#EXT-X-STREAM-INF:BANDWIDTH={bandwidth},"
                f"RESOLUTION={profile.width}x{profile.height},"
                f"NAME=\"{profile.name}\""
            )
            lines.append(f"{profile.name}/playlist.m3u8")
        
        with open(output_path, "w") as f:
            f.write("\n".join(lines) + "\n")
    
    def _parse_bitrate(self, bitrate: str) -> int:
        """
        Parse bitrate string to bits per second
        
        Args:
            bitrate: Bitrate string (e.g., "800k", "5M")
            
        Returns:
            Bitrate in bits per second
        """
        bitrate = bitrate.lower().strip()
        
        if bitrate.endswith("k"):
            return int(float(bitrate[:-1]) * 1000)
        elif bitrate.endswith("m"):
            return int(float(bitrate[:-1]) * 1000000)
        else:
            return int(bitrate)
    
    def cleanup(self, output_dir: str) -> None:
        """
        Clean up temporary files
        
        Args:
            output_dir: Directory to clean up
        """
        if os.path.exists(output_dir):
            shutil.rmtree(output_dir)
            logger.info(f"Cleaned up directory: {output_dir}")


# Singleton instance
hls_converter = HLSConverter()
