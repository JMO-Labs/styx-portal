"""Shared FastAPI dependencies for the instances routers."""
from app.config import Settings
from app.services.docker_manager import DockerManager
from app.services.k8s_runtime import instance_runtime
from app.services.screenshot import ScreenshotService

_settings = Settings()


def _dind_store_volume(instance_id: str) -> str:
    return f"selkies-{instance_id}-dockerstore"


def get_docker_manager():
    return instance_runtime()


def get_screenshot_service() -> ScreenshotService:
    return ScreenshotService(
        cache_dir=_settings.SCREENSHOT_CACHE_DIR,
        docker_manager=DockerManager(network_name=_settings.DOCKER_NETWORK),
    )
