# MeshBoard
Text-based Bulletin Board System (BBS) designed to run over the Meshtastic network.

## MeshBoard Setup

Follow these steps to set up and run the MeshBoard system on your Raspberry Pi.

### Steps to Get Started

#### 1. Update and upgrade your Raspberry Pi
```bash
sudo apt update && sudo apt upgrade -y
```

#### 2. Install required packages
```bash
sudo apt install python3-pip python3-serial git
```

#### 3. Install the Meshtastic Python library
```bash
pip3 install meshtastic
```

#### 4. Clone the BBS code from GitHub
```bash
git clone https://github.com/VeggieVampire/MeshBoard
```

#### 5. Navigate to the MeshBoard directory
```bash
cd MeshBoard
```

#### 6. Run the BBS system
```bash
python3 bbs_system.py
```

### System Overview

Once this setup is complete, the system will be ready to operate on the local mesh network via the USB-connected Meshtastic device.
