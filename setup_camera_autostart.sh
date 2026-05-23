#!/bin/bash
# Auto-start setup script for Camera Pi

echo "========================================="
echo "Camera Pi Auto-Start Setup"
echo "========================================="

echo ""
echo "Step 1: Copying service file to systemd..."
sudo cp /home/abc/kkk/hytech-camera.service /etc/systemd/system/

echo ""
echo "Step 2: Reloading systemd daemon..."
sudo systemctl daemon-reload

echo ""
echo "Step 3: Enabling camera service..."
sudo systemctl enable hytech-camera.service

echo ""
echo "Step 4: Starting camera service..."
sudo systemctl start hytech-camera.service

echo ""
echo "========================================="
echo "Setup complete! Checking status..."
echo "========================================="
sudo systemctl status hytech-camera.service --no-pager

echo ""
echo "========================================="
echo "Camera service is now configured!"
echo "========================================="
echo ""
echo "The camera will:"
echo "  1. Wait 60 seconds after boot"
echo "  2. Start sending camera data to Machine '1'"
echo "  3. Auto-restart if it fails"
echo ""
echo "To check logs:"
echo "  sudo journalctl -u hytech-camera.service -f"
echo ""
echo "To restart manually:"
echo "  sudo systemctl restart hytech-camera.service"
echo ""
echo "Reboot now to test:"
echo "  sudo reboot"
