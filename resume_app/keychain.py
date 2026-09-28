"""Small macOS Keychain boundary. Secrets never enter command arguments/files."""
import ctypes as C
import sys

SERVICE = b"resume-produce.deepseek"
ACCOUNT = b"default"


def _security():
    if sys.platform != "darwin":
        raise RuntimeError("钥匙串仅适用于 macOS；其他环境使用 DEEPSEEK_API_KEY。")
    lib = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
    lib.SecKeychainFindGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.POINTER(C.c_uint32), C.POINTER(C.c_void_p), C.POINTER(C.c_void_p)]
    lib.SecKeychainFindGenericPassword.restype = C.c_int32
    lib.SecKeychainAddGenericPassword.argtypes = [C.c_void_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_uint32, C.c_char_p, C.c_void_p]
    lib.SecKeychainAddGenericPassword.restype = C.c_int32
    lib.SecKeychainItemModifyAttributesAndData.argtypes = [C.c_void_p, C.c_void_p, C.c_uint32, C.c_char_p]
    lib.SecKeychainItemModifyAttributesAndData.restype = C.c_int32
    lib.SecKeychainItemFreeContent.argtypes = [C.c_void_p, C.c_void_p]
    lib.SecKeychainItemFreeContent.restype = C.c_int32
    return lib


def read_key(provider="deepseek"):
    from .models import PROVIDERS
    if provider not in PROVIDERS: raise ValueError("不支持的服务商")
    service = f"resume-produce.{provider}".encode()
    lib = _security()
    length, content = C.c_uint32(), C.c_void_p()
    code = lib.SecKeychainFindGenericPassword(None, len(service), service, len(ACCOUNT), ACCOUNT, C.byref(length), C.byref(content), None)
    if code == -25300:  # errSecItemNotFound
        return None
    if code:
        raise RuntimeError(f"钥匙串读取未完成（系统状态 {code}），请检查授权或重新配置。")
    try:
        return C.string_at(content, length.value).decode("utf-8")
    finally:
        lib.SecKeychainItemFreeContent(None, content)


def write_key(key, provider="deepseek"):
    from .models import PROVIDERS
    if provider not in PROVIDERS: raise ValueError("不支持的服务商")
    service = f"resume-produce.{provider}".encode()
    lib = _security()
    raw = key.encode("utf-8")
    item = C.c_void_p()
    code = lib.SecKeychainFindGenericPassword(None, len(service), service, len(ACCOUNT), ACCOUNT, None, None, C.byref(item))
    if code == -25300:
        code = lib.SecKeychainAddGenericPassword(None, len(service), service, len(ACCOUNT), ACCOUNT, len(raw), raw, None)
    elif code == 0:
        core = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        core.CFRelease.argtypes = [C.c_void_p]
        core.CFRelease.restype = None
        try:
            code = lib.SecKeychainItemModifyAttributesAndData(item, None, len(raw), raw)
        finally:
            core.CFRelease(item)
    if code:
        raise RuntimeError(f"钥匙串保存未完成（系统状态 {code}），请检查系统授权后重试。")
