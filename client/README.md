# Smart Sentinel - Client Viewer

View the Smart Sentinel live feed from another computer.

## Setup

1. Install Python 3.10+
2. Install dependencies:
   ```
   pip install -r ../requirements.txt
   ```

## Usage

```bash
# If server is on your own machine (testing):
python main.py

# Connect to a server on the network:
python main.py --url=http://SERVER_IP:8000
```

Replace `SERVER_IP` with the IP address of the machine running the server.
To find the server's IP, run `ipconfig` on the server machine and look for the IPv4 address under the WiFi adapter.

## Requirements

- Same WiFi network as the server
- Python 3.10+
- No webcam needed
- No GPU needed
