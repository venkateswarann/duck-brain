#!/usr/bin/env bash
# Turn the Pi 4 USB-C <-> Pi Zero USB cable into a private Ethernet link.
#
#   Pi 4  (USB host)    10.55.0.1/24   shares its internet with the Zero (NAT)
#   Zero  (USB gadget)  10.55.0.2/24
#
# Run once on each board, then reboot both:
#   sudo ./setup_usb_link.sh pi4
#   sudo ./setup_usb_link.sh zero
set -euo pipefail

ROLE="${1:-}"
BOOT=/boot/firmware
[[ -d "$BOOT" ]] || BOOT=/boot
CONFIG="$BOOT/config.txt"
CMDLINE="$BOOT/cmdline.txt"
# Fixed MACs so the Pi 4 side always gets the same interface (enx020000550001).
HOST_MAC="02:00:00:55:00:01"
DEV_MAC="02:00:00:55:00:02"
CON=usb-link

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo." >&2
  exit 1
fi

add_config_line() {
  local line="$1"
  local marker="# duck usb-link"
  # Only trust our own marked block: the stock config.txt can carry the same
  # line under [cm4]/[cm5] filters, where it doesn't apply to this board.
  if grep -qxF "$marker" "$CONFIG"; then
    echo "config.txt already has the usb-link block"
  else
    # [all] at the end so the line isn't swallowed by an earlier [pi4]/[cm4] filter.
    printf '\n[all]\n%s\n%s\n' "$marker" "$line" >>"$CONFIG"
    echo "config.txt += $line (in [all])"
  fi
}

case "$ROLE" in
  zero)
    add_config_line "dtoverlay=dwc2"
    if ! grep -q 'modules-load=dwc2,g_ether' "$CMDLINE"; then
      cp "$CMDLINE" "$CMDLINE.bak"
      sed -i "s/rootwait/rootwait modules-load=dwc2,g_ether g_ether.host_addr=$HOST_MAC g_ether.dev_addr=$DEV_MAC/" "$CMDLINE"
      echo "cmdline.txt += modules-load=dwc2,g_ether (backup: cmdline.txt.bak)"
    fi
    # Raspberry Pi OS marks USB gadget interfaces unmanaged; NetworkManager must own usb0.
    echo 'SUBSYSTEM=="net", KERNEL=="usb0", ENV{NM_UNMANAGED}="0"' >/etc/udev/rules.d/99-duck-usb-link.rules
    udevadm control --reload
    nmcli device set usb0 managed yes >/dev/null 2>&1 || true
    nmcli connection delete "$CON" >/dev/null 2>&1 || true
    # Route via the Pi 4 only as a last resort (metric 700), so Wi-Fi wins when present.
    nmcli connection add type ethernet con-name "$CON" ifname usb0 \
      ipv4.method manual ipv4.addresses 10.55.0.2/24 ipv4.gateway 10.55.0.1 \
      ipv4.dns 10.55.0.1 ipv4.route-metric 700 ipv6.method ignore \
      connection.autoconnect yes connection.autoconnect-priority 50 >/dev/null
    echo "NetworkManager: $CON on usb0 = 10.55.0.2/24"
    ;;
  pi4)
    # USB-C is the OTG port; host mode so the Zero enumerates as a USB network card.
    add_config_line "dtoverlay=dwc2,dr_mode=host"
    nmcli connection delete "$CON" >/dev/null 2>&1 || true
    # method=shared: static 10.55.0.1, DHCP/DNS via dnsmasq and NAT to whatever uplink the Pi 4 has.
    # Match by interface name, not MAC: g_ether offers ECM and RNDIS, and if the
    # host binds RNDIS the MAC is random. Priority beats NM's auto "Wired connection".
    nmcli -t -f NAME,DEVICE connection show | awk -F: '$2=="usb0" && $1!="'"$CON"'" {print $1}' |
      while read -r auto; do nmcli connection delete "$auto" >/dev/null; done
    nmcli connection add type ethernet con-name "$CON" ifname usb0 \
      ipv4.method shared ipv4.addresses 10.55.0.1/24 ipv6.method ignore \
      connection.autoconnect yes connection.autoconnect-priority 100 >/dev/null
    echo "NetworkManager: $CON on usb0 = 10.55.0.1/24, sharing internet"
    ;;
  *)
    echo "Usage: sudo $0 {pi4|zero}" >&2
    exit 1
    ;;
esac

echo "Done. Reboot this board; then from the Pi 4: ping 10.55.0.2"
