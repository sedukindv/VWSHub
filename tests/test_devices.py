"""Isolated protocol tests: no camera, recorder, SOAP or network connections."""
import copy
import sys
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

import pytest
from flask import Flask

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hub import devices


class Runtime:
    def __init__(self):
        self.me={"id":"admin","role":"admin"}
        self.camera={"id":"cam1","name":"Recorder","protocol":"dvrip","ip":"192.0.2.10","port":34567,"username":"admin","password":"encrypted","channel":0}
        self.events=[]
    def current_user(self):return self.me
    def get_camera(self,key):return self.camera if key==self.camera["id"] else None
    def audit(self,action,detail):self.events.append((action,detail))
    def dec_pwd(self,value):return "connection-password"
    def enc_pwd(self,value):return "enc:"+value


@pytest.fixture
def console(monkeypatch):
    runtime=Runtime();dvr=Mock();config={
        "General.General":{"OverWrite":"StopRecord","HostName":"Recorder","UnknownFirmwareFlag":17},
        "Record":[{"RecordMode":"ConfigRecord","PreRecord":4,"TimeSection":[["1 00:00:00-24:00:00","0 00:00:00-00:00:00"]],"FirmwarePrivate":101},
                  {"RecordMode":"ManualRecord","PreRecord":3,"FirmwarePrivate":102}],
        "NetWork.NetCommon":{"HostIP":"0x0A0200C0","Submask":"0x00FFFFFF","TCPPort":34567,"MAC":"00:11:22:33:44:55"},
        "General.AutoMaintain":{"AutoDeleteFilesDays":0,"AutoRebootHour":3,"AutoRebootDay":"Never"},
    }
    dvr.get_info.side_effect=lambda name:copy.deepcopy(config.get(name,{"Ret":104}))
    def save(name,value):config[name]=copy.deepcopy(value);return {"Ret":100}
    dvr.set_info.side_effect=save
    inventory={"Ret":100,"StorageInfo":[{"PlysicalNo":2,"Type":"SATA","Partition":[{"PartNo":1,"TotalSpace":"0x00100000","RemainSpace":"0x00080000","Status":"Normal"}]}]}
    dvr.send.side_effect=lambda code,payload:copy.deepcopy(inventory) if code==1020 else {"Ret":100}
    dvr.get_system_info.return_value={"DeviceType":"DVR","SerialNo":"12345","Password":"never-expose"}
    dvr.get_system_capabilities.return_value={"OtherFunction":[{"PTZControl":True}]}
    dvr.getUsers.return_value=[{"Name":"admin","Reserved":True,"Password":"secret-hash","Group":"admin"},{"Name":"viewer","Reserved":False,"Group":"user"}]
    dvr.getGroups.return_value=[{"Name":"admin"},{"Name":"user"}]
    dvr.changePasswd.return_value={"Ret":100};dvr.sofia_hash.return_value="old-hash"
    dvr.set_command.return_value={"Ret":100}
    connector=Mock(return_value=dvr);monkeypatch.setattr(devices,"connect_dvr",connector)
    soap=NS(services={});soap_connector=Mock(return_value=soap);monkeypatch.setattr(devices,"connect_onvif",soap_connector)
    app=Flask(__name__);app.config["TESTING"]=True;devices.register_devices(app,runtime)
    return NS(client=app.test_client(),app=app,runtime=runtime,dvr=dvr,config=config,inventory=inventory,connector=connector,soap=soap,soap_connector=soap_connector)


def post(c,path,**data):return c.client.post(path,json={"cam_id":"cam1",**data})


@pytest.mark.parametrize("role",[None,"viewer","operator"])
def test_only_administrator_can_read_or_write_hardware(console,role):
    console.runtime.me={"role":role} if role else None
    assert post(console,"/api/device/capabilities").status_code==403
    assert post(console,"/api/device/storage/format",confirm=True).status_code==403
    console.connector.assert_not_called()


def test_json_object_required_and_unknown_device_no_connection(console):
    assert console.client.post("/api/device/config",json=[]).status_code==400
    assert post(console,"/api/device/config",cam_id="missing").status_code==404
    console.connector.assert_not_called()


def test_config_read_has_revision_and_unknown_readonly(console):
    reply=post(console,"/api/device/config",section="general").get_json()
    assert len(reply["revision"])==64
    assert next(f for f in reply["fields"] if f["key"]=="UnknownFirmwareFlag")["editable"] is False
    console.dvr.set_info.assert_not_called()


def test_partial_patch_preserves_unknown_fields_and_other_channels(console):
    before=copy.deepcopy(console.config["Record"])
    reply=post(console,"/api/device/config",section="recording",channel=1).get_json()
    assert all(f["path"][0]==1 for f in reply["fields"])
    saved=post(console,"/api/device/config",section="recording",channel=1,revision=reply["revision"],confirm=True,changes=[{"path":[1,"PreRecord"],"value":8}])
    assert saved.status_code==200 and saved.get_json()["saved"] is True
    assert console.config["Record"][0]==before[0]
    assert console.config["Record"][1]["FirmwarePrivate"]==102
    assert console.config["Record"][1]["PreRecord"]==8


def test_optimistic_revision_prevents_lost_updates(console):
    reply=post(console,"/api/device/config",section="general").get_json()
    console.config["General.General"]["HostName"]="ChangedElsewhere"
    response=post(console,"/api/device/config",section="general",revision=reply["revision"],confirm=True,changes=[{"path":["OverWrite"],"value":"OverWrite"}])
    assert response.status_code==409
    console.dvr.set_info.assert_not_called()


@pytest.mark.parametrize("path,value",[([0,"PreRecord"],6),([1,"FirmwarePrivate"],0),([1,"Password"],"hack"),([True,"PreRecord"],6)])
def test_unknown_or_other_channel_fields_never_written(console,path,value):
    revision=devices._revision(console.config["Record"])
    response=post(console,"/api/device/config",section="recording",channel=1,revision=revision,confirm=True,changes=[{"path":path,"value":value}])
    assert response.status_code==400
    console.dvr.set_info.assert_not_called()


def test_unsupported_section_does_not_turn_ack_into_config(console):
    response=post(console,"/api/device/config",section="digital")
    assert response.status_code==501
    console.dvr.set_info.assert_not_called()


def test_ack_without_persisted_change_reports_unverified(console):
    console.dvr.set_info.side_effect=lambda *args:{"Ret":100}
    revision=devices._revision(console.config["General.General"])
    reply=post(console,"/api/device/config",section="general",revision=revision,confirm=True,changes=[{"path":["OverWrite"],"value":"OverWrite"}])
    assert reply.status_code==200 and reply.get_json()["saved"] is False


def test_network_requires_typed_device_name_and_preserves_ip_wire_format(console):
    revision=devices._revision(console.config["NetWork.NetCommon"])
    payload=dict(section="network",revision=revision,confirm=True,changes=[{"path":["HostIP"],"value":"192.0.2.25"}])
    assert post(console,"/api/device/config",**payload).status_code==400
    console.dvr.set_info.assert_not_called()
    reply=post(console,"/api/device/config",device_name="Recorder",**payload)
    assert reply.status_code==200
    assert console.config["NetWork.NetCommon"]["HostIP"]=="0x190200C0"
    assert console.config["NetWork.NetCommon"]["MAC"]=="00:11:22:33:44:55"


@pytest.mark.parametrize("value",["foo;reboot","$(reboot)","safe\nreboot","`reboot`",""])
def test_hostname_metacharacters_rejected(value):
    with pytest.raises(ValueError):devices.patch_config({"HostName":"safe"},"general",[{"path":["HostName"],"value":value}])


@pytest.mark.parametrize("value",["1 24:01:00-24:00:00","1 21:00:00-20:00:00","1 00:60:00-24:00:00","1 00:00:00-24:01:00"])
def test_invalid_schedule_not_written(value):
    with pytest.raises(ValueError):devices.patch_config([{"TimeSection":[["1 00:00:00-24:00:00"]]}],"recording",[{"path":[0,"TimeSection",0,0],"value":value}],0)


def test_disabled_schedule_and_end_of_day_preserved():
    current=[{"TimeSection":[["1 00:00:00-24:00:00"]]}]
    result=devices.patch_config(current,"recording",[{"path":[0,"TimeSection",0,0],"value":"0 00:00:00-00:00:00"}],0)
    assert result[0]["TimeSection"][0][0]=="0 00:00:00-00:00:00"
    assert current[0]["TimeSection"][0][0]=="1 00:00:00-24:00:00"


@pytest.mark.parametrize("invalid",[True,"NaN",float("inf"),-1,31])
def test_recording_numeric_type_and_documented_bounds(invalid):
    with pytest.raises(ValueError):devices.patch_config({"PreRecord":4},"recording",[{"path":["PreRecord"],"value":invalid}])


def test_capabilities_are_actual_flags_and_hide_secrets(console):
    reply=post(console,"/api/device/capabilities").get_json()
    assert reply["capabilities"]["ptz"] is True
    assert "Password" not in reply["system_info"]
    assert all(section["supported"] is None for section in reply["sections"])
    console.dvr.get_info.assert_not_called()


def test_storage_inventory_uses_real_reported_partition(console):
    reply=post(console,"/api/device/storage").get_json()
    disk=reply["disks"][0]
    assert (disk["serial"],disk["partition"],disk["total_mb"],disk["kind"])==(2,1,1048576,"hdd")
    assert "ВСЕХ" in reply["warning"] and "SD" in reply["warning"]


@pytest.mark.parametrize("change",[{"confirm":False},{"confirmation":"yes"},{"device_name":"wrong"},{"serial":0},{"partition":0}])
def test_format_needs_all_confirmations_and_fresh_inventory(console,change):
    body={"confirm":True,"confirmation":"ERASE_ALL_RECORDINGS","device_name":"Recorder","serial":2,"partition":1,**change}
    assert post(console,"/api/device/storage/format",**body).status_code==400
    assert not any(call.args[0]==1460 for call in console.dvr.send.call_args_list)


def test_format_only_selected_verified_partition(console):
    response=post(console,"/api/device/storage/format",confirm=True,confirmation="ERASE_ALL_RECORDINGS",device_name="Recorder",serial=2,partition=1)
    assert response.status_code==200
    console.dvr.send.assert_called_with(1460,{"Name":"OPStorageManager","OPStorageManager":{"Action":"Clear","SerialNo":2,"PartNo":1}})
    assert console.runtime.events[-1][0]=="device.storage.format"


def test_auto_delete_retention_requires_device_name(console):
    revision=devices._revision(console.config["General.AutoMaintain"])
    response=post(console,"/api/device/config",section="maintenance",revision=revision,confirm=True,changes=[{"path":["AutoDeleteFilesDays"],"value":10}])
    assert response.status_code==400
    console.dvr.set_info.assert_not_called()


def test_dhcp_arrays_are_interfaces_not_video_channels(console):
    console.config["NetWork.NetDHCP"]=[{"Interface":"eth0","Enable":True},{"Interface":"eth1","Enable":False}]
    reply=post(console,"/api/device/config",section="dhcp",channel=7).get_json()
    assert reply["scope"]=="interface" and reply["channel_count"] is None
    assert {f["context"] for f in reply["fields"]}=={"eth0","eth1"}
    response=post(console,"/api/device/config",section="dhcp",channel=7,revision=reply["revision"],confirm=True,device_name="Recorder",changes=[{"path":[1,"Enable"],"value":True}])
    assert response.status_code==200 and console.config["NetWork.NetDHCP"][1]["Enable"] is True


def test_device_user_password_uses_explicit_old_password_and_not_connection_hash(console):
    body=dict(action="password",username="viewer",password="new-secret",confirm=True)
    assert post(console,"/api/device/users",**body).status_code==400
    console.dvr.changePasswd.assert_not_called()
    response=post(console,"/api/device/users",old_password="viewer-old",**body)
    assert response.status_code==200
    console.dvr.sofia_hash.assert_called_with("viewer-old")
    console.dvr.changePasswd.assert_called_with(newpass="new-secret",oldpass="old-hash",user="viewer")
    assert "Password" not in response.get_json()["users"][0]
    assert all("secret" not in detail and "viewer-old" not in detail for _,detail in console.runtime.events)


def test_current_connection_account_cannot_be_deleted(console):
    assert post(console,"/api/device/users",action="delete",username="admin",confirm=True).status_code==400
    console.dvr.delUser.assert_not_called()


def test_dvr_ptz_step_guarantees_stop_with_same_channel_and_direction(console,monkeypatch):
    monkeypatch.setattr(devices.time,"sleep",lambda seconds:None)
    reply=post(console,"/api/device/ptz",action="move",pan=.5,tilt=0,zoom=0,channel=3)
    assert reply.status_code==200
    calls=console.dvr.set_command.call_args_list
    assert len(calls)==2
    assert all(call.args[1]["Command"]=="DirectionRight" and call.args[1]["Parameter"]["Channel"]==3 for call in calls)
    assert calls[-1].args[1]["Parameter"]["Preset"]==-1


def test_onvif_ptz_timeout_and_explicit_stop(console):
    console.runtime.camera["protocol"]="onvif"
    media=Mock();ptz=Mock();media.GetProfiles.return_value=[NS(token="p1",PTZConfiguration=NS(token="ptz1"))]
    console.soap.services={"media":media,"ptz":ptz}
    assert post(console,"/api/device/ptz",action="move",pan=.3,zoom=.1).status_code==200
    command=ptz.ContinuousMove.call_args.args[0]
    assert command["ProfileToken"]=="p1" and command["Timeout"].total_seconds()==.8
    assert command["Velocity"]["Zoom"]=={"x":.1}
    assert post(console,"/api/device/ptz",action="stop").status_code==200
    ptz.Stop.assert_called_once_with({"ProfileToken":"p1","PanTilt":True,"Zoom":True})


def test_onvif_password_change_preserves_existing_admin_role(console):
    console.runtime.camera["protocol"]="onvif";device=Mock();device.GetUsers.return_value=[NS(Username="admin",UserLevel="Administrator")]
    console.soap.services={"devicemgmt":device}
    response=post(console,"/api/device/users",action="password",username="admin",password="new-password",confirm=True)
    assert response.status_code==200
    device.SetUser.assert_called_once_with({"User":[{"Username":"admin","Password":"new-password","UserLevel":"Administrator"}]})


def test_encoder_choices_filtered_by_actual_channel_mask():
    ability={"EncodeInfo":[{"StreamType":"MainStream","Enable":True,"CompressionMask":"0x80","ResolutionMask":"0x9"}],"ImageSizePerChannel":["0x1","0x8"]}
    assert devices.encoder_choices(ability,[1,"MainFormat","Video","Resolution"],"Resolution",1)==["CIF"]
    assert devices.encoder_choices(None,[],"Resolution",1)==[]
    fields=devices.describe_config([{"MainFormat":{"Video":{"Compression":"H.264","Resolution":"D1"}}}],"encoder",0,None)
    assert not any(f["editable"] for f in fields)


def test_credential_bearing_errors_are_not_echoed(console):
    console.dvr.get_system_info.side_effect=RuntimeError("rtsp://admin:secret@192.0.2.10/live")
    response=post(console,"/api/device/capabilities")
    assert response.status_code==502 and "secret" not in response.get_data(as_text=True)


def test_only_one_route_for_profiles_no_camera_test_shadow(console):
    urls=[rule.rule for rule in console.app.url_map.iter_rules()]
    assert urls.count("/api/onvif/profiles")==1
    assert "/api/cameras/test" not in urls


def test_reboot_requires_ack_keeps_control_link_and_blocks_duplicates(console):
    response=post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder")
    assert response.status_code==200 and response.json["accepted"] is True
    assert response.json["verification_required"] is True
    console.dvr.set_command.assert_called_once_with("OPMachine",{"Action":"Reboot"})
    console.dvr._wait_for_disconnect.assert_called_once_with(15)
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder").status_code==409
    assert console.dvr.set_command.call_count==1


def test_reboot_refusal_does_not_report_success(console):
    console.dvr.set_command.return_value={"Ret":104}
    response=post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder")
    assert response.status_code==502
    console.dvr._wait_for_disconnect.assert_not_called()


def test_reboot_without_confirmation_never_sends_command(console):
    assert post(console,"/api/device/system",action="reboot").status_code==400
    console.dvr.set_command.assert_not_called()


def test_summary_network_is_decoded_without_mutating_wire_config(console):
    console.dvr.get_netcommon.return_value={"HostIP":"0x320611AC","GateWay":"0x0A0611AC"}
    response=post(console,"/api/device/system",action="read")
    assert response.json["network_display"]=={"HostIP":"172.17.6.50","GateWay":"172.17.6.10"}
    assert response.json["network"]["HostIP"]=="0x320611AC"


def test_unknown_and_unconfirmed_geometry_have_no_guessed_editor():
    fields=devices.describe_config({"AutoLogout":0,"FrontColor":"0xFFFFFFFF","RelativePos":[0,1,2,3],"Enable":True},"osd")
    assert all(not f["display"] for f in fields if f["key"]!="Enable")
    assert all(not f["editable"] for f in fields if f["key"]!="Enable")


def test_ntp_ip_uses_network_byte_order_and_preserves_unknown():
    current={"Enable":True,"Server":{"Address":"0x0A0611AC","Name":"ntp.example.test","Private":4}}
    fields=devices.describe_config(current,"ntp")
    assert next(f for f in fields if f["key"]=="Address")["value"]=="172.17.6.10"
    updated=devices.patch_config(current,"ntp",[{"path":["Server","Address"],"value":"172.17.6.50"}])
    assert updated["Server"]["Address"]=="0x320611AC" and updated["Server"]["Private"]==4


@pytest.mark.parametrize("reply",[{},True,{"Ret":515},{"Ret":150}])
def test_reboot_requires_exact_reboot_ack(console,reply):
    console.dvr.set_command.return_value=reply
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder").status_code==502
    console.dvr._wait_for_disconnect.assert_not_called()


def test_reboot_name_must_match_before_device_connection(console):
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Different").status_code==400
    console.connector.assert_not_called()


def test_reboot_resets_management_evidence_and_read_restores_it(console):
    from hub.store import DataStore
    key=DataStore.connection_key(console.runtime.camera)
    assert post(console,"/api/device/system",action="read").status_code==200
    assert console.runtime.device_health[key]["management_checked"]>0
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder").status_code==200
    assert console.runtime.device_health[key]["management_checked"]==0


def test_onvif_reboot_confirmation_and_cooldown(console):
    console.runtime.camera["protocol"]="onvif"
    device=Mock();device.SystemReboot.return_value="Rebooting"
    console.soap.services={"devicemgmt":device}
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder").status_code==200
    assert post(console,"/api/device/system",action="reboot",confirm=True,device_name="Recorder").status_code==409
    device.SystemReboot.assert_called_once()


def test_vendor_timezone_code_has_no_guessed_iana_editor():
    descriptor=devices.describe_config({"TimeZone":14},"location")[0]
    assert descriptor["editable"] is False and descriptor["display"] is False
    with pytest.raises(ValueError):devices.patch_config({"TimeZone":14},"location",[{"path":["TimeZone"],"value":15}])


def test_hardware_timeout_is_structured_without_exception_secrets(console):
    console.dvr.get_system_info.side_effect=TimeoutError("rtsp://admin:secret@192.0.2.10/live")
    response=post(console,"/api/device/system",action="read")
    assert response.status_code==504
    assert response.json["error_code"]=="timeout" and response.json["stage"]=="system"
    assert "secret" not in response.get_data(as_text=True)


def test_onvif_network_writes_only_changes_preserves_extra_addresses_and_reads_back(console):
    console.runtime.camera["protocol"]="onvif"
    cfg={"DHCP":False,"Manual":[{"Address":"192.0.2.10","PrefixLength":24},{"Address":"192.0.2.11","PrefixLength":24}]}
    device=Mock();device.GetNetworkInterfaces.side_effect=lambda:[{"token":"eth0","IPv4":{"Config":copy.deepcopy(cfg)},"IPv6":{"Enabled":True}}]
    def save(value):cfg.update(copy.deepcopy(value["NetworkInterface"]["IPv4"]));return {"RebootNeeded":False}
    device.SetNetworkInterfaces.side_effect=save;console.soap.services={"devicemgmt":device}
    reply=post(console,"/api/device/onvif/network",settings={"token":"eth0","dhcp":False,"address":"192.0.2.12","prefix":24},confirm=True,device_name="Recorder")
    assert reply.status_code==200 and reply.json["saved"] is True
    assert cfg["Manual"]==[{"Address":"192.0.2.12","PrefixLength":24},{"Address":"192.0.2.11","PrefixLength":24}]
    device.SetDNS.assert_not_called();device.SetNetworkDefaultGateway.assert_not_called()
    payload=device.SetNetworkInterfaces.call_args.args[0]
    assert set(payload["NetworkInterface"])=={"IPv4"}


def test_onvif_network_unchanged_configuration_has_no_writes(console):
    console.runtime.camera["protocol"]="onvif"
    device=Mock();device.GetNetworkInterfaces.return_value=[{"token":"eth0","IPv4":{"Config":{"DHCP":True}}}]
    console.soap.services={"devicemgmt":device}
    response=post(console,"/api/device/onvif/network",settings={"token":"eth0","dhcp":True},confirm=True,device_name="Recorder")
    assert response.status_code==200 and response.json["saved"] is True
    device.SetNetworkInterfaces.assert_not_called();device.SetDNS.assert_not_called()


def test_onvif_network_ack_without_changed_readback_is_not_reported_saved(console):
    console.runtime.camera["protocol"]="onvif"
    device=Mock();device.GetNetworkInterfaces.return_value=[{"token":"eth0","IPv4":{"Config":{"DHCP":True}}}]
    device.SetNetworkInterfaces.return_value={"RebootNeeded":False};console.soap.services={"devicemgmt":device}
    response=post(console,"/api/device/onvif/network",settings={"token":"eth0","dhcp":False,"address":"192.0.2.12","prefix":24},confirm=True,device_name="Recorder")
    assert response.status_code==200 and response.json["saved"] is False and response.json["accepted"] is True
    assert response.json["verification_pending"] is True


def test_management_health_updates_preserve_media_evidence_and_clear_on_timeout(console):
    from hub.store import DataStore
    key=DataStore.connection_key(console.runtime.camera)
    console.runtime.device_health={key:{"archive_sources":{"cam1":10}}}
    assert post(console,"/api/device/system",action="read").status_code==200
    assert console.runtime.device_health[key]["archive_sources"]=={"cam1":10}
    console.dvr.get_system_info.side_effect=TimeoutError("synthetic transport timeout")
    assert post(console,"/api/device/system",action="read").status_code==504
    assert console.runtime.device_health[key]["management_checked"]==0


@pytest.mark.parametrize("name",["ntp://pool.example.test","pool.example.test:123","host/path","bad host"])
def test_ntp_server_name_rejects_urls_ports_and_spaces(name):
    with pytest.raises(ValueError):devices.patch_config({"Server":{"Name":"pool.example.test"}},"ntp",[{"path":["Server","Name"],"value":name}])


def test_dvrip_time_requires_local_clock_and_verifies_readback(console):
    from datetime import datetime
    assert post(console,"/api/device/system",action="time",utc="2026-11-03T12:00:00Z").status_code==400
    console.dvr.set_time.return_value={"Ret":100}
    console.dvr.get_time.return_value=datetime(2026,11,3,12,0,0)
    response=post(console,"/api/device/system",action="time",local_time="2026-11-03T12:00:00")
    assert response.status_code==200 and response.json["saved"] is True
    console.dvr.get_time.return_value=datetime(2026,11,3,11,0,0)
    response=post(console,"/api/device/system",action="time",local_time="2026-11-03T12:00:00")
    assert response.json["saved"] is False and response.json["accepted"] is True


def test_onvif_time_reports_unconfirmed_readback_honestly(console):
    console.runtime.camera["protocol"]="onvif"
    device=Mock();device.GetSystemDateAndTime.return_value={"UTCDateTime":{"Date":{"Year":2026,"Month":11,"Day":3},"Time":{"Hour":12,"Minute":0,"Second":0}},"DaylightSavings":False}
    console.soap.services={"devicemgmt":device}
    assert post(console,"/api/device/system",action="time",utc="2026-11-03T12:00:00Z").json["saved"] is True
    assert post(console,"/api/device/system",action="time",utc="2026-11-03T13:00:00Z").json["saved"] is False


@pytest.fixture
def ntp_console(console):
    console.runtime.camera["protocol"]="onvif"
    device=Mock()
    console.ntp={"FromDHCP":False,"NTPManual":[{"Type":"DNS","DNSname":"pool.example.test","Extension":{"Private":17}}],"Extension":{"Keep":9}}
    console.clock={"DateTimeType":"Manual","DaylightSavings":True,"TimeZone":{"TZ":"CET-1CEST"},"UTCDateTime":{"Date":{"Year":2026,"Month":11,"Day":3},"Time":{"Hour":12,"Minute":0,"Second":0}}}
    device.GetNTP.side_effect=lambda:copy.deepcopy(console.ntp)
    device.GetServiceCapabilities.return_value={"Network":{"NTP":3}}
    device.GetSystemDateAndTime.side_effect=lambda:copy.deepcopy(console.clock)
    device.SetNTP.side_effect=lambda value:console.ntp.update(copy.deepcopy(value))
    device.SetSystemDateAndTime.side_effect=lambda value:console.clock.update(copy.deepcopy(value))
    console.soap.services={"devicemgmt":device};console.device=device
    return console


def ntp_save(c,settings,**extra):
    revision=post(c,"/api/device/onvif/ntp").json["revision"]
    return post(c,"/api/device/onvif/ntp",settings=settings,revision=revision,confirm=True,**extra)


def test_onvif_ntp_capability_read_and_noop(ntp_console):
    c=ntp_console
    data=post(c,"/api/device/onvif/ntp").json
    assert data["writable"] and data["mode_writable"] and data["max_servers"]==3
    assert data["servers"]==["pool.example.test"] and data["enabled"] is False
    assert ntp_save(c,{}).json["saved"] is True
    c.device.SetNTP.assert_not_called();c.device.SetSystemDateAndTime.assert_not_called()


@pytest.mark.parametrize("maximum",[None,0,True,"3",-1,257])
def test_onvif_ntp_without_positive_capability_is_readonly(ntp_console,maximum):
    c=ntp_console;c.device.GetServiceCapabilities.return_value={"Network":{"NTP":maximum}}
    assert post(c,"/api/device/onvif/ntp").json["writable"] is False
    assert ntp_save(c,{"from_dhcp":True}).status_code==501
    c.device.SetNTP.assert_not_called()


def test_onvif_ntp_unsupported_safe_failure(ntp_console):
    c=ntp_console;c.device.GetNTP.side_effect=RuntimeError("ter:ActionNotSupported")
    assert post(c,"/api/device/onvif/ntp").status_code==501
    c.device.SetNTP.assert_not_called()


def test_onvif_ntp_revision_confirm_and_unknown_rejected(ntp_console):
    c=ntp_console
    assert post(c,"/api/device/onvif/ntp",settings={},revision="stale",confirm=True).status_code==409
    assert post(c,"/api/device/onvif/ntp",settings={}).status_code==400
    assert ntp_save(c,{"port":123}).status_code==400
    c.device.SetNTP.assert_not_called()


@pytest.mark.parametrize("settings",[
    {"servers":["https://pool.example.test"]},{"servers":["pool.example.test:123"]},
    {"servers":["pool.example.test/path"]},{"servers":[" pool.example.test"]},
    {"servers":["a b"]},{"servers":["a","A."]},{"servers":["a","b","c","d"]},
    {"servers":[123]},{"servers":["fe80::1%eth0"]},{"servers":"pool.example.test"},{"from_dhcp":1},{"enabled":1},
    {"servers":[],"enabled":True},
])
def test_onvif_ntp_validates_everything_before_write(ntp_console,settings):
    c=ntp_console
    assert ntp_save(c,settings).status_code==400
    c.device.SetNTP.assert_not_called();c.device.SetSystemDateAndTime.assert_not_called()


def test_onvif_ntp_changed_only_merge_preserves_extensions(ntp_console):
    c=ntp_console;before=copy.deepcopy(c.ntp)
    result=ntp_save(c,{"servers":["POOL.EXAMPLE.TEST.","192.0.2.123","2001:db8::123"]})
    assert result.status_code==200 and result.json["saved"] is True
    value=c.device.SetNTP.call_args.args[0]
    assert value["NTPManual"][0]==before["NTPManual"][0]
    assert value["NTPManual"][1]=={"Type":"IPv4","IPv4Address":"192.0.2.123"}
    assert value["NTPManual"][2]=={"Type":"IPv6","IPv6Address":"2001:db8::123"}
    assert c.ntp["Extension"]==before["Extension"]
    c.device.SetSystemDateAndTime.assert_not_called()


def test_onvif_ntp_dhcp_partial_preserves_manual_hosts(ntp_console):
    c=ntp_console;before=copy.deepcopy(c.ntp["NTPManual"])
    assert ntp_save(c,{"from_dhcp":True}).json["saved"] is True
    assert c.ntp["NTPManual"]==before


def test_onvif_ntp_mode_only_preserves_timezone_and_clock(ntp_console):
    c=ntp_console;before=copy.deepcopy(c.clock)
    assert ntp_save(c,{"enabled":True}).json["saved"] is True
    c.device.SetNTP.assert_not_called()
    assert c.device.SetSystemDateAndTime.call_args.args[0]=={"DateTimeType":"NTP","DaylightSavings":True,"TimeZone":before["TimeZone"]}
    assert ntp_save(c,{"enabled":False}).json["saved"] is True
    assert c.device.SetSystemDateAndTime.call_args.args[0]["UTCDateTime"]==before["UTCDateTime"]


def test_onvif_ntp_disable_requires_actual_utc_before_any_write(ntp_console):
    c=ntp_console;c.clock["DateTimeType"]="NTP";del c.clock["UTCDateTime"]
    assert ntp_save(c,{"enabled":False,"from_dhcp":True}).status_code==501
    c.device.SetNTP.assert_not_called();c.device.SetSystemDateAndTime.assert_not_called()


def test_onvif_ntp_ack_without_readback_is_not_saved(ntp_console):
    c=ntp_console;c.device.SetNTP.side_effect=None
    result=ntp_save(c,{"from_dhcp":True})
    assert result.status_code==200 and result.json["accepted"] is True
    assert result.json["saved"] is False and result.json["verification_pending"] is True


def test_onvif_ntp_unknown_host_cannot_be_overwritten(ntp_console):
    c=ntp_console;c.ntp["NTPManual"].append({"Type":"vendor","Address":"opaque"})
    assert post(c,"/api/device/onvif/ntp").json["writable"] is False
    assert ntp_save(c,{"servers":["new.example.test"]}).status_code==501
    c.device.SetNTP.assert_not_called()


def test_onvif_ntp_mode_requires_complete_current_clock(ntp_console):
    c=ntp_console;del c.clock["DaylightSavings"]
    assert post(c,"/api/device/onvif/ntp").json["mode_writable"] is False
    assert ntp_save(c,{"enabled":True}).status_code==501
    c.device.SetSystemDateAndTime.assert_not_called()


def test_onvif_ntp_mode_ack_does_not_claim_success(ntp_console):
    c=ntp_console;c.device.SetSystemDateAndTime.side_effect=None
    result=ntp_save(c,{"enabled":True})
    assert result.json["accepted"] is True and result.json["saved"] is False


def test_onvif_ntp_write_optional_operation_fault_is_unsupported(ntp_console):
    c=ntp_console;c.device.SetNTP.side_effect=RuntimeError("ter:OptionalActionNotImplemented")
    assert ntp_save(c,{"from_dhcp":True}).status_code==501


def test_onvif_ntp_cannot_be_accessed_by_operator(ntp_console):
    c=ntp_console;c.runtime.me={"role":"operator"}
    assert post(c,"/api/device/onvif/ntp").status_code==403
    c.soap_connector.assert_not_called()


def test_onvif_ntp_capability_matches_confirmed_device_support(ntp_console):
    c=ntp_console
    c.device.GetCapabilities.return_value={}
    c.soap.services["media"]=NS(GetProfiles=lambda:[])
    caps=post(c,"/api/device/capabilities").json["capabilities"]
    assert caps["ntp_read"] is True and caps["ntp"] is True
    c.device.GetNTP.side_effect=RuntimeError("ActionNotSupported")
    caps=post(c,"/api/device/capabilities").json["capabilities"]
    assert caps["ntp_read"] is False and caps["ntp"] is False


@pytest.fixture
def onvif_settings_console(console):
    c=console;c.runtime.camera["protocol"]="onvif"
    c.hostname="old-host";c.imaging_state={"Brightness":50,"Contrast":40}
    c.encoder_state=NS(token="encoder",Encoding="H264",Resolution=NS(Width=1280,Height=720),
        RateControl=NS(FrameRateLimit=10,BitrateLimit=1000),Quality=4,Extension=NS(VendorFlag=77))
    c.device=Mock();c.media=Mock();c.imaging=Mock()
    c.media.GetProfiles.return_value=[NS(token="profile",VideoSourceConfiguration=NS(SourceToken="sensor"),VideoEncoderConfiguration=NS(token="encoder"))]
    c.media.GetVideoEncoderConfiguration.side_effect=lambda *args:copy.deepcopy(c.encoder_state)
    c.media.GetVideoEncoderConfigurationOptions.return_value=NS(H264=NS(FrameRateRange=NS(Min=1,Max=30),
        BitrateRange=NS(Min=100,Max=10000),ResolutionsAvailable=[NS(Width=1280,Height=720),NS(Width=1920,Height=1080)]),
        Extension=None,QualityRange=NS(Min=1,Max=6))
    def encoder_save(data):c.encoder_state=copy.deepcopy(data["Configuration"])
    c.media.SetVideoEncoderConfiguration.side_effect=encoder_save
    c.imaging.GetOptions.return_value={key:{"Min":0,"Max":100} for key in c.imaging_state}
    c.imaging.GetImagingSettings.side_effect=lambda *args:copy.deepcopy(c.imaging_state)
    c.imaging.SetImagingSettings.side_effect=lambda data:c.imaging_state.update(data["ImagingSettings"])
    c.device.GetHostname.side_effect=lambda:{"Name":c.hostname,"FromDHCP":False}
    def hostname_save(data):c.hostname=data["Name"].lower()
    c.device.SetHostname.side_effect=hostname_save
    c.soap.services={"devicemgmt":c.device,"media":c.media,"imaging":c.imaging}
    return c


ONVIF_WRITES=[("imaging",{"settings":{"Brightness":75}}),
              ("encoder",{"settings":{"fps":25,"bitrate":2000,"quality":4.5,"width":1920,"height":1080}}),
              ("hostname",{"hostname":"New-Host"})]


@pytest.mark.parametrize("kind,payload",ONVIF_WRITES)
def test_onvif_write_reports_saved_only_after_matching_readback(onvif_settings_console,kind,payload):
    c=onvif_settings_console
    reply=post(c,"/api/device/"+kind,**payload)
    assert reply.status_code==200
    assert reply.json["accepted"] is True and reply.json["saved"] is True
    assert reply.json["readback_available"] is True and reply.json["verification_pending"] is False
    if kind=="hostname":
        c.device.GetHostname.assert_called_once();assert reply.json["hostname"]=="new-host"
    elif kind=="encoder":
        sent=c.media.SetVideoEncoderConfiguration.call_args.args[0]
        assert sent["Configuration"].Extension.VendorFlag==77


@pytest.mark.parametrize("kind,payload",ONVIF_WRITES)
def test_onvif_setter_ack_without_persistence_cannot_report_saved(onvif_settings_console,kind,payload):
    c=onvif_settings_console
    setter={"imaging":c.imaging.SetImagingSettings,"encoder":c.media.SetVideoEncoderConfiguration,"hostname":c.device.SetHostname}[kind]
    setter.side_effect=None
    reply=post(c,"/api/device/"+kind,**payload)
    assert reply.status_code==200 and reply.json["accepted"] is True
    assert reply.json["saved"] is False and reply.json["verification_pending"] is True
    assert reply.json["readback_available"] is True
    setter.assert_called_once()


@pytest.mark.parametrize("kind,payload",ONVIF_WRITES)
def test_onvif_readback_failure_preserves_accepted_but_unverified_result(onvif_settings_console,kind,payload):
    c=onvif_settings_console
    error=TimeoutError("rtsp://admin:private-password@192.0.2.10/live")
    if kind=="encoder":c.media.GetVideoEncoderConfiguration.side_effect=[copy.deepcopy(c.encoder_state),error]
    elif kind=="imaging":c.imaging.GetImagingSettings.side_effect=error
    else:c.device.GetHostname.side_effect=error
    reply=post(c,"/api/device/"+kind,**payload)
    assert reply.status_code==200 and reply.json["accepted"] is True
    assert reply.json["saved"] is False and reply.json["verification_pending"] is True
    assert reply.json["readback_available"] is False
    assert "private-password" not in reply.get_data(as_text=True)


def test_onvif_readback_verifies_only_requested_fields(onvif_settings_console):
    c=onvif_settings_console
    def save(data):
        c.encoder_state=copy.deepcopy(data["Configuration"])
        c.encoder_state.Quality=6 # An unrelated firmware adjustment is not our patch.
    c.media.SetVideoEncoderConfiguration.side_effect=save
    reply=post(c,"/api/device/encoder",settings={"fps":25})
    assert reply.json["saved"] is True and reply.json["settings"]["quality"]==6


@pytest.mark.parametrize("kind",["imaging","encoder"])
def test_onvif_plain_read_failure_is_not_hidden_as_an_accepted_write(onvif_settings_console,kind):
    c=onvif_settings_console
    if kind=="imaging":c.imaging.GetImagingSettings.side_effect=TimeoutError("synthetic read timeout")
    else:c.media.GetVideoEncoderConfiguration.side_effect=TimeoutError("synthetic read timeout")
    reply=post(c,"/api/device/"+kind)
    assert reply.status_code==504 and "accepted" not in reply.json
