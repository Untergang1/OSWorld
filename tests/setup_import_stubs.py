import sys
import types


def install_setup_controller_stubs():
    playwright_stub = types.ModuleType("playwright")
    sync_api_stub = types.ModuleType("playwright.sync_api")
    sync_api_stub.sync_playwright = lambda: None
    sync_api_stub.TimeoutError = TimeoutError
    sys.modules.setdefault("playwright", playwright_stub)
    sys.modules.setdefault("playwright.sync_api", sync_api_stub)

    pydrive_stub = types.ModuleType("pydrive")
    pydrive_auth_stub = types.ModuleType("pydrive.auth")
    pydrive_drive_stub = types.ModuleType("pydrive.drive")
    pydrive_auth_stub.GoogleAuth = object
    pydrive_drive_stub.GoogleDrive = object
    pydrive_drive_stub.GoogleDriveFile = object
    pydrive_drive_stub.GoogleDriveFileList = object
    sys.modules.setdefault("pydrive", pydrive_stub)
    sys.modules.setdefault("pydrive.auth", pydrive_auth_stub)
    sys.modules.setdefault("pydrive.drive", pydrive_drive_stub)

    requests_toolbelt_stub = types.ModuleType("requests_toolbelt")
    requests_toolbelt_multipart_stub = types.ModuleType("requests_toolbelt.multipart")
    requests_toolbelt_encoder_stub = types.ModuleType("requests_toolbelt.multipart.encoder")
    requests_toolbelt_encoder_stub.MultipartEncoder = object
    sys.modules.setdefault("requests_toolbelt", requests_toolbelt_stub)
    sys.modules.setdefault("requests_toolbelt.multipart", requests_toolbelt_multipart_stub)
    sys.modules.setdefault("requests_toolbelt.multipart.encoder", requests_toolbelt_encoder_stub)

    metrics_utils_stub = types.ModuleType("desktop_env.evaluators.metrics.utils")
    metrics_utils_stub.compare_urls = lambda *args, **kwargs: False
    sys.modules.setdefault("desktop_env.evaluators.metrics.utils", metrics_utils_stub)

    proxy_pool_stub = types.ModuleType("desktop_env.providers.aws.proxy_pool")
    proxy_pool_stub.get_global_proxy_pool = lambda *args, **kwargs: None
    proxy_pool_stub.init_proxy_pool = lambda *args, **kwargs: None
    proxy_pool_stub.ProxyInfo = object
    sys.modules.setdefault("desktop_env.providers.aws.proxy_pool", proxy_pool_stub)
