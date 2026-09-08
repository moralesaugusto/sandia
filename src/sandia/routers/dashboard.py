from fastapi import APIRouter, Depends, Request
from sqlmodel import Session, select

from ..config import Settings, get_settings
from ..config_store import load_live_config
from ..db import get_session
from ..devices import DeviceStatus, build_devices
from ..dhcpd import apply as apply_module
from ..diagnostics import load_dhcp_events
from ..leases import load_lease_history, load_leases
from ..models import AuditLog, User
from ..rendering import render
from ..security import require_login
from ..utilization import subnet_utilization

router = APIRouter()


@router.get("/")
async def dashboard(
    request: Request,
    user: User = Depends(require_login),
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
):
    config = load_live_config(settings)
    leases = load_leases(settings.leases_path)
    subnet_rows = []
    for subnet in config.subnets:
        used, total = subnet_utilization(subnet, leases)
        subnet_rows.append({"subnet": subnet, "used": used, "total": total})

    status = await apply_module.service_status(settings)
    recent_audit = session.exec(select(AuditLog).order_by(AuditLog.timestamp.desc()).limit(10)).all()

    lease_history = load_lease_history(settings.leases_path)
    events, _ = load_dhcp_events(settings)
    devices = build_devices(config, leases, lease_history, events)
    problem_device_count = sum(1 for device in devices if device.status == DeviceStatus.PROBLEM)

    return render(
        request,
        "dashboard.html",
        user=user,
        subnet_rows=subnet_rows,
        service_status=status,
        recent_audit=recent_audit,
        lease_count=len(leases),
        active_lease_count=sum(1 for lease in leases if lease.is_active),
        reservation_count=len(config.all_hosts),
        at_risk_count=sum(1 for row in subnet_rows if row["total"] and row["used"] / row["total"] >= 0.9),
        device_count=len(devices),
        problem_device_count=problem_device_count,
    )
