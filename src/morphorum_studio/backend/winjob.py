"""Ties a child process to Studio's lifetime with a Windows job object.

When the job handle closes (Studio exits or crashes), Windows ends every process in the job, so
the backend and anything it started can never be left running by accident. Other systems get a
harmless no-op. Failures are reported as False, never raised.
"""
from __future__ import annotations

import os

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
PROCESS_SET_QUOTA = 0x0100
PROCESS_TERMINATE = 0x0001


class JobObject:
    def __init__(self) -> None:
        self._handle = None
        self._kernel = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class _Basic(ctypes.Structure):
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD)]

            class _IoCounters(ctypes.Structure):
                _fields_ = [(n, ctypes.c_uint64) for n in (
                    "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                    "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

            class _Extended(ctypes.Structure):
                _fields_ = [("BasicLimitInformation", _Basic), ("IoInfo", _IoCounters),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateJobObjectW.restype = wintypes.HANDLE
            kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
            kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
            kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = kernel.CreateJobObjectW(None, None)
            if not handle:
                return
            info = _Extended()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not kernel.SetInformationJobObject(handle, JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
                                                  ctypes.byref(info), ctypes.sizeof(info)):
                kernel.CloseHandle(handle)
                return
            self._kernel, self._handle = kernel, handle
        except (OSError, AttributeError, ImportError):
            self._kernel = self._handle = None

    @property
    def available(self) -> bool:
        return self._handle is not None

    def assign(self, pid: int) -> bool:
        """Put the process in the job. False if that is not possible (it keeps running either way)."""
        if self._handle is None or self._kernel is None or not pid:
            return False
        try:
            process = self._kernel.OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, False, int(pid))
            if not process:
                return False
            try:
                return bool(self._kernel.AssignProcessToJobObject(self._handle, process))
            finally:
                self._kernel.CloseHandle(process)
        except OSError:
            return False

    def close(self) -> None:
        """Close the job; Windows then ends everything in it. Called implicitly when Studio exits."""
        if self._handle is not None and self._kernel is not None:
            self._kernel.CloseHandle(self._handle)
        self._handle = None
