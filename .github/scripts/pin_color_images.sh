#!/usr/bin/env bash
# Prints the production Deployment manifest with each color's image set to the
# image that color runs now, so kubectl apply leaves a running color alone. An
# empty image keeps the manifest's value, which covers a first deploy.
#
# Usage: pin_color_images.sh <manifest> <blue-image> <green-image>
set -euo pipefail

awk -v blue="$2" -v green="$3" '
  /^---/ { image = "" }
  /^  name: github-tamagotchi-blue$/ { image = blue }
  /^  name: github-tamagotchi-green$/ { image = green }
  /^ +image: / && image != "" { sub(/image: .*/, "image: " image) }
  { print }
' "$1"
