from __future__ import annotations

import typer

from synology_site.commands import tunnel_fix
from synology_site.commands.backup_plan import app as backup_plan_app
from synology_site.commands.bootstrap_n8n import app as bootstrap_n8n_app
from synology_site.commands.bootstrap_supabase import app as bootstrap_supabase_app
from synology_site.commands.bootstrap_umami import app as bootstrap_umami_app
from synology_site.commands.bootstrap_uptime_kuma import app as bootstrap_uptime_kuma_app
from synology_site.commands.bootstrap_vaultwarden import app as bootstrap_vaultwarden_app
from synology_site.commands.check_nas import app as check_nas_app
from synology_site.commands.cloudflare_route import app as cloudflare_route_app
from synology_site.commands.configure_tailscale import app as configure_tailscale_app
from synology_site.commands.create import app as create_app
from synology_site.commands.deploy import app as deploy_app
from synology_site.commands.health import app as health_app
from synology_site.commands.list_sites import app as list_app
from synology_site.commands.migrate_from_lightsail import app as migrate_from_lightsail_app
from synology_site.commands.registry_login import app as registry_login_app
from synology_site.commands.remove import app as remove_app
from synology_site.commands.start import app as start_app
from synology_site.commands.stop import app as stop_app
from synology_site.commands.update import app as update_app
from synology_site.commands.workspaces import app as workspaces_app

app = typer.Typer(help="Deploy containerized sites to a Synology NAS.")

app.command(name="create")(create_app)
app.command(name="deploy")(deploy_app)
app.command(name="update")(update_app)
app.command(name="registry-login")(registry_login_app)
app.command(name="cloudflare-route")(cloudflare_route_app)
app.command(name="bootstrap-supabase")(bootstrap_supabase_app)
app.command(name="bootstrap-n8n")(bootstrap_n8n_app)
app.command(name="bootstrap-umami")(bootstrap_umami_app)
app.command(name="bootstrap-uptime-kuma")(bootstrap_uptime_kuma_app)
app.command(name="bootstrap-vaultwarden")(bootstrap_vaultwarden_app)
app.command(name="check-nas")(check_nas_app)
app.command(name="configure-tailscale")(configure_tailscale_app)
app.command(name="health")(health_app)
app.command(name="backup-plan")(backup_plan_app)
app.command(name="list")(list_app)
app.command(name="start")(start_app)
app.command(name="stop")(stop_app)
app.command(name="remove")(remove_app)
app.command(name="cloudflare-instructions")(tunnel_fix.cloudflare_instructions)
app.command(name="tunnel-fix-autostart")(tunnel_fix.tunnel_fix_autostart)
app.command(name="set-autostart")(tunnel_fix.set_autostart)
app.command(name="workspaces")(workspaces_app)
app.command(name="migrate-from-lightsail")(migrate_from_lightsail_app)


def main() -> None:
    app()
