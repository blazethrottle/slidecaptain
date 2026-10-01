"""Pin Windows directory names while history uses path-based OS functions.

Windows lacks Python dir_fd operations. Open every resolved ancestor without
FILE_SHARE_DELETE, preventing rename/replacement for the lifetime of the read.
No creation, write access, or privilege elevation is requested.
"""

from contextlib import contextmanager
from pathlib import Path
import stat


@contextmanager
def pinned_directory(directory: Path):
    import ctypes
    from ctypes import wintypes

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    final_path = kernel.GetFinalPathNameByHandleW
    final_path.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
    final_path.restype = wintypes.DWORD
    invalid = ctypes.c_void_p(-1).value
    handles = []
    resolved = directory.resolve(strict=True)
    def name_of(handle):
        size = final_path(handle, None, 0, 0)
        if not size:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(size + 1)
        result = final_path(handle, buffer, len(buffer), 0)
        if not result or result >= len(buffer):
            raise OSError("Cannot resolve opened handle")
        return buffer.value

    class Pinned:
        path = resolved
        expected = ""

        def verify_handle(self, handle, name):
            # Validate the handle before reading bytes, not the path that opened it.
            # A junction may be installed in-place even while rename is denied.
            if name_of(handle) != str(Path(self.expected) / name):
                raise OSError("Opened file is outside the pinned directory")

        def verify_fd(self, fd, name):
            import msvcrt
            self.verify_handle(msvcrt.get_osfhandle(fd), name)

        def verify_entry(self, name):
            # Metadata-only opens also bind enumerated names before returning them.
            handle = create(str(resolved / name), 0x80, 0x1 | 0x2 | 0x4, None, 3,
                            0x02000000 | 0x00200000, None)
            if handle == invalid:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                self.verify_handle(handle, name)
            finally:
                close(handle)

    pinned = Pinned()
    try:
        for path in [*reversed(resolved.parents), resolved]:
            # FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES, share READ|WRITE,
            # OPEN_EXISTING,
            # BACKUP_SEMANTICS (directories) | OPEN_REPARSE_POINT (no final symlink).
            # Attribute-only access is exempt from Windows sharing checks;
            # listing access makes the omitted FILE_SHARE_DELETE block rename.
            handle = create(str(path), 0x1 | 0x80, 0x1 | 0x2, None, 3, 0x02000000 | 0x00200000, None)
            if handle == invalid:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                raise OSError("Not a direct directory")
        pinned.expected = name_of(handles[-1])
        yield pinned
    finally:
        for handle in reversed(handles):
            close(handle)
