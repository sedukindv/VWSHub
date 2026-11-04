"""TEST ONLY: deterministic hardware behind the real administrative API routes.

No socket, SOAP, recorder, reboot or format operation is performed. Call install
only in a dedicated TESTING application; never import this from product code.
"""
from copy import deepcopy
from types import SimpleNamespace as NS


class FakeDVR:
    def __init__(self):
        self.actions = []
        self.clock = "2026-11-03 12:00:00"
        self.users = [{"Name": "admin", "Group": "admin", "Reserved": True},
                      {"Name": "test-viewer", "Group": "user", "Reserved": False}]
        video = {"Video": {"Compression": "H.264", "Resolution": "D1", "FPS": 18,
                           "BitRate": 2048, "BitRateControl": "CBR", "Quality": 4},
                 "VideoEnable": True, "AudioEnable": False}
        self.config = {
            "General.General": {"HostName": "TEST-ONLY-DVR", "OverWrite": "OverWrite", "UnknownFirmwareFlag": 7},
            "General.Location": {"DateFormat": "YYMMDD", "DateSeparator": "-", "TimeFormat": "24", "TimeZone": 14},
            "NetWork.NetNTP": {"Enable": True, "Server": {"Address": "0x00000000", "Name": "ntp.example.test", "Port": 123}, "UpdatePeriod": 720},
            "NetWork.NetCommon": {"HostIP": "0x0A0200C0", "Submask": "0x00FFFFFF", "GateWay": "0x010200C0", "HostName": "TEST-ONLY-DVR", "TCPPort": 34567, "HttpPort": 80, "MAC": "00:00:5e:00:53:01"},
            "NetWork.NetDHCP": [{"Interface": "eth0", "Enable": False}],
            "NetWork.NetDNS": {"Address": "0x010200C0", "SpareAddress": "0x020200C0"},
            "Record": [{"RecordMode": "ConfigRecord", "PreRecord": 5, "PacketLength": 30, "PrivateFlag": 8,
                        "TimeSection": [["1 00:00:00-24:00:00"] for _ in range(7)]} for _ in range(32)],
            "Simplify.Encode": [{"MainFormat": deepcopy(video), "ExtraFormat": deepcopy(video)} for _ in range(32)],
            "AVEnc.VideoWidget": [{"ChannelTitle": {"Name": f"TEST CH {i+1}", "PreviewBlend": True}, "Covers": [{"FrontColor": "0xFFFFFFFF", "RelativePos": [0, 0, 100, 100]}]} for i in range(32)],
            "AVEnc.VideoColor": [{"Brightness": 50, "Contrast": 50, "Saturation": 50, "Sharpness": 50} for _ in range(32)],
            "General.AutoMaintain": {"AutoRebootDay": "Never", "AutoRebootHour": 3, "AutoDeleteFilesDays": 0},
            # Digital-channel configuration intentionally unsupported, exercising
            # the real route's safe 501 / read-only presentation.
        }

    def close(self): pass
    def get_time(self): return self.clock
    def set_time(self, value):
        self.actions.append(("time",)); self.clock = value.isoformat(); return {"Ret": 100}
    def get_system_info(self):
        return {"DeviceType": "TEST ONLY DVR", "HardWare": "SYNTHETIC", "SerialNo": "TEST-NO-HARDWARE",
                "SoftWareVersion": "fixture-0.9", "VideoInChannel": 24, "DigChannel": 8, "PrivateFlag": 7}
    def get_system_capabilities(self): return {"OtherFunction": [{"PTZControl": True}]}
    def get_netcommon(self): return self.get_info("NetWork.NetCommon")
    def get_info(self, name): return deepcopy(self.config.get(name, {"Ret": 104}))
    def set_info(self, name, value):
        self.actions.append(("config", name)); self.config[name] = deepcopy(value); return {"Ret": 100}
    def get_encode_capabilities(self):
        return {"EncodeInfo": [{"StreamType": name, "Enable": True, "CompressionMask": "0x80", "ResolutionMask": "0x1"} for name in ("MainStream", "ExtraStream2")],
                "ImageSizePerChannel": ["0x1"] * 32, "ExImageSizePerChannel": ["0x1"] * 32}
    def getUsers(self): return deepcopy(self.users)
    def getGroups(self): return [{"Name": "admin"}, {"Name": "user"}]
    def addUser(self, name, password, **kwargs):
        self.actions.append(("user.create", name)); self.users.append({"Name": name, "Group": kwargs.get("group", "user"), "Reserved": False}); return {"Ret": 100}
    def modifyUser(self, name, **kwargs):
        self.actions.append(("user.update", name))
        for user in self.users:
            if user["Name"] == name: user["Group"] = kwargs.get("group", user["Group"])
        return {"Ret": 100}
    def delUser(self, name):
        self.actions.append(("user.delete", name)); self.users = [u for u in self.users if u["Name"] != name]; return {"Ret": 100}
    def changePasswd(self, **kwargs): self.actions.append(("user.password",)); return {"Ret": 100}
    def sofia_hash(self, value): return "TEST-NO-SECRET-HASH"
    def set_command(self, name, value): self.actions.append(("command", name)); return {"Ret": 100}
    def _wait_for_disconnect(self, seconds): self.actions.append(("wait.mock", seconds))
    def send(self, code, payload):
        if code == 1020:
            return {"Ret": 100, "StorageInfo": [{"PlysicalNo": 0, "Type": "SATA", "Partition": [{"PartNo": 0, "TotalSpace": "0x00100000", "RemainSpace": "0x00080000", "Status": "Normal"}]}]}
        self.actions.append(("send.mock", code)); return {"Ret": 100}


class FakeONVIF:
    def __init__(self):
        self.actions = []
        interface = {"token": "eth0", "Enabled": True, "Info": {"Name": "TEST ONLY", "HwAddress": "00:00:5e:00:53:02"}, "IPv4": {"Config": {"DHCP": False, "Manual": [{"Address": "192.0.2.44", "PrefixLength": 24}]}}}
        clock = {"DateTimeType":"Manual", "TimeZone":{"TZ":"UTC0"}, "UTCDateTime": {"Date": {"Year": 2026, "Month": 11, "Day": 3}, "Time": {"Hour": 12, "Minute": 0, "Second": 0}}, "DaylightSavings": False}
        ntp = {"FromDHCP":False,"NTPManual":[{"Type":"DNS","DNSname":"pool.example.test","Extension":{"FixtureFlag":7}}]}
        dns={"FromDHCP":False,"DNSManual":[{"Type":"IPv4","IPv4Address":"192.0.2.1"}]}
        gateway={"IPv4Address":["192.0.2.1"]}
        def set_time(value):
            self.actions.append(("time.mock",))
            clock.update(deepcopy(value))
        def set_ntp(value):
            self.actions.append(("ntp.mock",));ntp.update(deepcopy(value))
        def set_interface(value):
            self.actions.append(("network.mock",))
            interface["IPv4"]["Config"]=deepcopy(value["NetworkInterface"]["IPv4"])
            return {"RebootNeeded":False}
        def set_dns(value):
            self.actions.append(("dns.mock",));dns.clear();dns.update(deepcopy(value))
        def set_gateway(value):
            self.actions.append(("gateway.mock",));gateway.clear();gateway.update(deepcopy(value))
        device = NS(GetCapabilities=lambda *args: NS(PTZ=None, Imaging=None),
                    GetServiceCapabilities=lambda: {"Network":{"NTP":2}},
                    GetNTP=lambda: deepcopy(ntp),SetNTP=set_ntp,
                    GetDeviceInformation=lambda: {"Manufacturer": "TEST ONLY", "Model": "SYNTHETIC ONVIF", "FirmwareVersion": "fixture-0.9"},
                    GetSystemDateAndTime=lambda: deepcopy(clock), SetSystemDateAndTime=set_time,
                    GetNetworkInterfaces=lambda: [deepcopy(interface)], GetNetworkDefaultGateway=lambda: deepcopy(gateway),
                    GetDNS=lambda: deepcopy(dns),
                    GetUsers=lambda: [{"Username": "admin", "UserLevel": "Administrator"}],
                    SystemReboot=lambda: self.actions.append(("reboot.mock",)) or "TEST ONLY",
                    SetNetworkInterfaces=set_interface,
                    SetNetworkDefaultGateway=set_gateway,
                    SetDNS=set_dns)
        self.services = {"devicemgmt": device, "media": NS(GetProfiles=lambda: [NS(token="test-profile", Name="TEST ONLY", VideoSourceConfiguration=None, VideoEncoderConfiguration=None, PTZConfiguration=None)])}


def install(app, runtime):
    if not app.testing:
        raise RuntimeError("Hardware fixture requires a dedicated TESTING app")
    from hub import devices
    from hub.store import DataStore
    models = {}
    def dvr(_runtime, camera):
        return models.setdefault(("dvr", DataStore.connection_key(camera)), FakeDVR())
    def onvif(_runtime, camera):
        return models.setdefault(("onvif", DataStore.connection_key(camera)), FakeONVIF())
    devices.connect_dvr = dvr
    devices.connect_onvif = onvif
    app.extensions["wvw_test_hardware"] = models
    return models
