# EVE-NG Link Manager

## Why I Built This

I run a large EVE-NG lab with 141 nodes for our LogZilla testing, and manually suspending interfaces one-by-one was tedious to click each link and suspend, then re-enable in order to generate failures, bgp re-routing, etc. So I made this.

Now I can just type `r7,e0/0` and boom - link down. No more hunting for numeric IDs or clicking.

The best part? I can create a simple text file with all the links I want to mess with and take them down or bring them up with a single command. Makes chaos testing way more fun when you're not drowning in the chaos yourself ;)

I use it mostly for LogZilla demos (showing how monitoring catches network issues and automatically fixes them), but it's handy for any EVE-NG lab where you need to simulate failures without the hassle.

## What It Does

This tool allows you to automate suspending and resuming interfaces in your EVE-NG lab without manually clicking in the UI.

## Features

- **User-Friendly Interface**: Use device names and interface names (e.g., "r7,e0/0") instead of numeric IDs
- **Interface Control**: Suspend, resume, or flap (toggle) interfaces
- **Batch Operations**: Perform actions on multiple interfaces from a file
- **Dry Run Mode**: Test commands without actually modifying interfaces
- **Direct EVE-NG Control**: Uses unl_wrapper to directly control EVE-NG interfaces

## Prerequisites

- Python 3.6+
- Root/sudo access on the EVE-NG host (for interface management)
- Required Python packages (see requirements.txt):
  - eve-ng
  - python-dotenv
  - requests

## Installation

1. Clone or copy this directory to your EVE-NG server
2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Make the script executable:
   ```
   chmod +x eve_link_manager.py
   ```

## Usage

### First-time Setup

1. Create a .env file using the provided template:

```bash
cp .env.example .env
```

2. Edit the .env file with your EVE-NG connection details:

> Note: use relative paths for the lab file, leave out `/opt/unetlab/labs/`
```
EVE_HOST=localhost
EVE_USERNAME=admin
EVE_PASSWORD=eve
EVE_LAB="/Labs/mylab.unl"
```

### Common Operations

#### View Node and Interface Inventory

```bash
# View the complete inventory of nodes and interfaces in the lab
python eve_link_manager.py inventory --lab "/Labs/mylab.unl"

# You can also enable debug logging for more detailed output
python eve_link_manager.py --debug inventory --lab "/Labs/mylab.unl"
```

#### Suspend an Interface

```bash
# Suspend interface using device ID and interface ID (if you know them)
python eve_link_manager.py suspend --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl"

# Suspend with dry run to see what would happen without actually executing
python eve_link_manager.py suspend --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl" --dry-run
```

#### Resume an Interface

```bash
python eve_link_manager.py resume --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl"
```

#### Batch Operations

Create a file with interfaces to suspend/resume, one per line. The file can use two formats:

**Simple format (device_name,interface_name):**
```
# Format: device_name,interface_name
r4,e0/0
r7,e0/0
r24,e0/1
sw35,e0/2
```
With this format, the script will automatically look up the device ID and interface ID using the EVE-NG API.

**Full ID format (device_id,interface_id,device2_id,interface2_id):**
```
# Format: device_id,interface_id,device2_id,interface2_id
7,0,9,0
24,16,17,16
```
This format is useful if you already know the EVE-NG numeric IDs.

Then run the batch command:

```bash
# Suspend all interfaces in the file with dry-run (preview only)
python eve_link_manager.py batch --operation suspend --file interfaces.txt --lab "/Labs/mylab.unl" --dry-run

# Actually suspend the interfaces
python eve_link_manager.py batch --operation suspend --file interfaces.txt --lab "/Labs/mylab.unl"

# Resume the interfaces later
python eve_link_manager.py batch --operation resume --file interfaces.txt --lab "/Labs/mylab.unl"

# Flap all interfaces in the file once
python eve_link_manager.py batch --operation flap --file interfaces.txt --lab "/Labs/mylab.unl"

# Flap all interfaces in the file three times with a 2-second delay
python eve_link_manager.py batch --operation flap --file interfaces.txt --lab "/Labs/mylab.unl" --count 3 --delay 2
```

### Custom Environment File

If you have multiple environment configurations, you can specify a custom .env file:

```bash
python eve_link_manager.py --env-file production.env inventory --lab "/Labs/mylab.unl"
```

## Demo Scenarios

### Targeted Interface Suspensions

Create a file of critical interfaces to suspend for testing failover scenarios:

```bash
# Create a file called critical_interfaces.txt
# Format: device_name,interface_name
r4,e0/0  # Core router uplink
r7,e0/0  # WAN connection
r24,e0/1 # Datacenter connection

# Suspend them all at once
python eve_link_manager.py batch --operation suspend --file critical_interfaces.txt --lab "/Labs/mylab.unl"

# Resume them all at once when testing is complete
python eve_link_manager.py batch --operation resume --file critical_interfaces.txt --lab "/Labs/mylab.unl"
```

### Link Flapping

To flap (suspend then resume) an interface:

```bash
# Flap interface e0/0 on device r7 once
python eve_link_manager.py flap --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl"

# Flap interface e0/0 on device r7 three times with a 2-second delay
python eve_link_manager.py flap --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl" --count 3 --delay 2

# Preview what would happen without actually flapping (dry run)
python eve_link_manager.py flap --device-id 7 --interface-id 0 --lab "/Labs/mylab.unl" --dry-run
```

The flap command suspends the interface, waits for the specified delay period, then resumes it. This is repeated based on the count parameter.

## Troubleshooting

- If you're having issues with permissions, make sure you're running the script with sudo
- If you get "Lab does not exist" errors, check your lab path format. The API is sensitive to formatting.
- Use the `--dry-run` flag to preview commands without executing them
- Run with python's `-m pdb` flag to debug complex issues: `python -m pdb eve_link_manager.py ...`
- Check EVE-NG logs at `/opt/unetlab/data/Logs/` if you encounter persistent issues
