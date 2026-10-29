#!/usr/bin/env bash
# PoC: Xorg の画面全体を撮る
DISPLAY=:0 XAUTHORITY="/run/user/$(id -u)/gdm/Xauthority" import -window root "$1"
