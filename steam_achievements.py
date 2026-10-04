"""Isolated native Steam UserStats bridge; loads only the installed game's DLL.

No SDK binaries, achievement catalogue, account identifiers or credentials are
distributed. Call run() in a disposable worker, never the web server process.
"""
import ctypes as C
import os
from pathlib import Path
import re
import time
import game_data

APP_ID = 3306200

class Callback(C.Structure):
    _fields_ = [('user', C.c_int), ('event', C.c_int),
                ('data', C.c_void_p), ('size', C.c_int)]

class StatsReceived(C.Structure):
    _fields_ = [('game', C.c_uint64), ('result', C.c_int), ('user', C.c_uint64)]

class StatsStored(C.Structure):
    _fields_ = [('game', C.c_uint64), ('result', C.c_int)]

def validate_request(action, achievement=None, confirmed=False):
    if action not in ('list', 'unlock'):
        raise ValueError('未知 Steam 操作')
    if action == 'unlock' and (confirmed is not True or not isinstance(achievement, str)
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', achievement)):
        raise ValueError('必须确认一个有效的成就 ID')

class Steam:
    def __init__(self, dll):
        self.dll = dll
        def bind(name, result, *args):
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = result, args
            return fn
        ptr, char, boolean = C.c_void_p, C.c_char_p, C.c_bool
        self.init = bind('SteamAPI_InitFlat', C.c_int, ptr)
        self.shutdown = bind('SteamAPI_Shutdown', None)
        self.manual_init = bind('SteamAPI_ManualDispatch_Init', None)
        self.pipe = bind('SteamAPI_GetHSteamPipe', C.c_int)
        self.frame = bind('SteamAPI_ManualDispatch_RunFrame', None, C.c_int)
        self.next = bind('SteamAPI_ManualDispatch_GetNextCallback', boolean, C.c_int, C.POINTER(Callback))
        self.free = bind('SteamAPI_ManualDispatch_FreeLastCallback', None, C.c_int)
        # These interface versions are verified against this game's local DLL.
        self.stats = bind('SteamAPI_SteamUserStats_v012', ptr)()
        self.utils = bind('SteamAPI_SteamUtils_v010', ptr)()
        self.appid = bind('SteamAPI_ISteamUtils_GetAppID', C.c_uint32, ptr)
        self.request = bind('SteamAPI_ISteamUserStats_RequestCurrentStats', boolean, ptr)
        self.count = bind('SteamAPI_ISteamUserStats_GetNumAchievements', C.c_uint32, ptr)
        self.name = bind('SteamAPI_ISteamUserStats_GetAchievementName', char, ptr, C.c_uint32)
        self.attr = bind('SteamAPI_ISteamUserStats_GetAchievementDisplayAttribute', char, ptr, char, char)
        self.get = bind('SteamAPI_ISteamUserStats_GetAchievementAndUnlockTime', boolean,
                        ptr, char, C.POINTER(boolean), C.POINTER(C.c_uint32))
        self.set = bind('SteamAPI_ISteamUserStats_SetAchievement', boolean, ptr, char)
        self.store = bind('SteamAPI_ISteamUserStats_StoreStats', boolean, ptr)

    def wait(self, event, record, timeout=20):
        deadline = time.monotonic() + timeout
        pipe = self.pipe()
        while time.monotonic() < deadline:
            self.frame(pipe)
            msg = Callback()
            while self.next(pipe, C.byref(msg)):
                try:
                    if msg.event == event and msg.size >= C.sizeof(record) and msg.data:
                        result = record.from_buffer_copy(C.string_at(msg.data, C.sizeof(record)))
                        if result.game == APP_ID:
                            if result.result != 1:
                                raise ValueError('Steam 返回错误代码 ' + str(result.result))
                            return
                finally:
                    self.free(pipe)
            time.sleep(0.05)
        raise ValueError('等待 Steam 回调超时；请检查 Steam 登录、网络后刷新状态')

    def entries(self):
        count = self.count(self.stats)
        if not 0 < count <= 2000:
            raise ValueError('Steam 未返回有效成就目录')
        entries = []
        for i in range(count):
            key = self.name(self.stats, i)
            if not key:
                raise ValueError('Steam 成就 ID 缺失')
            unlocked, timestamp = C.c_bool(), C.c_uint32()
            if not self.get(self.stats, key, C.byref(unlocked), C.byref(timestamp)):
                raise ValueError('Steam 无法读取成就状态')
            def attr(name):
                return (self.attr(self.stats, key, name.encode()) or b'').decode('utf-8', 'replace')
            entries.append({'id': key.decode('utf-8'), 'name': attr('name'),
                'description': attr('desc'), 'hidden': attr('hidden') == '1',
                'unlocked': unlocked.value, 'time': timestamp.value})
        return entries

def operate(api, action, achievement=None):
    """Explicit mutation boundary, independently testable without real writes."""
    if not api.request(api.stats):
        raise ValueError('Steam 拒绝读取统计数据')
    api.wait(1101, StatsReceived)
    entries = api.entries()
    if action == 'list':
        return {'appid': APP_ID, 'entries': entries, 'write': False}
    selected = next((e for e in entries if e['id'] == achievement), None)
    if selected is None:
        raise ValueError('成就 ID 不在 Steam 返回的本游戏目录中')
    if selected['unlocked']:
        return {'appid': APP_ID, 'achievement': selected, 'already_unlocked': True, 'write': False}
    if not api.set(api.stats, achievement.encode('utf-8')):
        raise ValueError('Steam SetAchievement 拒绝解锁')
    if not api.store(api.stats):
        raise ValueError('Steam StoreStats 提交失败；请刷新核对状态')
    api.wait(1102, StatsStored)
    if not api.request(api.stats):
        raise ValueError('已提交，但再次读取状态失败；请刷新核对')
    api.wait(1101, StatsReceived)
    current = next(e for e in api.entries() if e['id'] == achievement)
    if not current['unlocked']:
        raise ValueError('已提交，但 Steam 回读未确认解锁；请刷新核对')
    return {'appid': APP_ID, 'achievement': current, 'write': True, 'stored': True}

def run(action, game=None, achievement=None, confirmed=False):
    validate_request(action, achievement, confirmed)
    if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
        raise ValueError('Steam 功能需要 Windows 64 位 Python')
    install = game_data.find_install(Path('.local') / 'unused.sd', game)
    dll_path = install / 'cs_Data/Plugins/x86_64/steam_api64.dll'
    if not dll_path.is_file():
        raise ValueError('本机游戏 Steam DLL 缺失')
    kernel = C.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.argtypes = [C.c_void_p, C.c_bool, C.c_wchar_p]
    kernel.CreateMutexW.restype = C.c_void_p
    kernel.CloseHandle.argtypes = [C.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\CoffeeShopEditorSteam3306200')
    if not mutex:
        raise OSError('无法建立 Steam 操作锁')
    existing = C.get_last_error() == 183
    api, started = None, False
    try:
        if existing:
            raise ValueError('另一个 Steam 操作正在运行，请稍后重试')
        # Worker-only environment; no steam_appid.txt in the game or source tree.
        os.environ['SteamAppId'] = os.environ['SteamGameId'] = str(APP_ID)
        with os.add_dll_directory(str(dll_path.parent)):
            dll = C.CDLL(str(dll_path))
        # Initialize before obtaining interface pointers.
        init = dll.SteamAPI_InitFlat
        init.argtypes, init.restype = [C.c_void_p], C.c_int
        error = C.create_string_buffer(1024)
        if init(error) != 0:
            raise ValueError('Steam 初始化失败；请登录 Steam 并确认拥有本游戏。' + error.value.decode('utf-8', 'replace'))
        started = True
        api = Steam(dll)
        if not api.stats or not api.utils or api.appid(api.utils) != APP_ID:
            raise ValueError('Steam 游戏接口或 AppID 不匹配，操作已停止')
        api.manual_init()
        return operate(api, action, achievement)
    finally:
        if started:
            dll.SteamAPI_Shutdown()
        kernel.CloseHandle(mutex)
