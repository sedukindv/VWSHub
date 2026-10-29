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
