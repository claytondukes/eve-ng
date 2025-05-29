#!/usr/bin/env python3
"""
EVE-NG Link Manager

A tool for managing links in EVE-NG labs, allowing you to suspend and resume interfaces
to generate events for LogZilla demos without manually clicking in the UI.

This script automates:
1. Retrieving all nodes and their interfaces from an EVE-NG lab
2. Mapping EVE-NG interfaces to host interfaces
3. Suspending or resuming links via the host CLI
"""

import argparse
import subprocess
import os
import sys
import json
import time
import logging
from typing import Dict, List, Tuple, Optional
from getpass import getpass
from dotenv import load_dotenv

try:
    from evengsdk.client import EvengClient
except ImportError:
    print("Error: eve-ng package not found. Please install it using:\npip install eve-ng")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('eve_link_manager')


def connect_to_eveng(host: str, username: str, password: str) -> EvengClient:
    """Establish a connection to the EVE-NG server"""
    logger.info(f"Connecting to EVE-NG server: {host}")
    try:
        # Connect to EVE-NG server using EvengClient
        # The protocol is https, ssl_verify=False for self-signed certs
        cli = EvengClient(host, protocol="https", ssl_verify=False)
        cli.disable_insecure_warnings()  # Disable warnings for self-signed certificates
        cli.login(username=username, password=password)
        logger.info("Successfully connected to EVE-NG")
        return cli
    except Exception as e:
        logger.error(f"Failed to connect to EVE-NG: {str(e)}")
        sys.exit(1)


def get_lab_inventory(client: EvengClient, lab_path: str) -> Dict:
    """Retrieve a complete inventory of nodes and interfaces from the lab"""
    logger.info(f"Retrieving inventory for lab: {lab_path}")
    try:
        # Get all nodes in the lab through the client.api interface
        nodes_response = client.api.list_nodes(lab_path)
        
        if nodes_response.get('status') != 'success':
            logger.error(f"Failed to get nodes: {nodes_response}")
            sys.exit(1)
            
        nodes = nodes_response.get('data', {})
        
        # Build a complete inventory with node interfaces
        inventory = {}
        total_interfaces = 0
        
        for node_id, node in nodes.items():
            inventory[node_id] = {
                'name': node['name'],
                'interfaces': {}
            }
            
            # Get interfaces for this node
            try:
                interfaces_response = client.api.get_node_interfaces(lab_path, node_id)
                
                # Debug: Show sample interface response for diagnostic purposes
                if node_id in ['1', '2'] and interfaces_response.get('status') == 'success':
                    logger.debug(f"DEBUG: Sample interface data for node {node['name']} (ID: {node_id}):")
                    interfaces = interfaces_response.get('data', {})
                    for if_type, if_data in interfaces.items():
                        logger.debug(f"  Interface type: {if_type}: {if_data}")
                
                if interfaces_response.get('status') == 'success':
                    interfaces = interfaces_response.get('data', {})
                    
                    # Process each interface type (ethernet, serial, etc.)
                    for if_type, if_data in interfaces.items():
                        if isinstance(if_data, dict):
                            # Process nested interfaces
                            for sub_id, sub_if in if_data.items():
                                if isinstance(sub_if, dict):
                                    # Create a unique ID for this interface
                                    unique_if_id = f"{if_type}_{sub_id}"
                                    if_name = sub_if.get('name', f"{if_type}{sub_id}")
                                    network_id = sub_if.get('network_id', 0)
                                    
                                    # Store interface information
                                    inventory[node_id]['interfaces'][unique_if_id] = {
                                        'name': if_name,
                                        'network_id': network_id
                                    }
                                    total_interfaces += 1
            except Exception as iface_error:
                logger.warning(f"Failed to get interfaces for node {node['name']}: {str(iface_error)}")
        
        logger.info(f"Retrieved {len(inventory)} nodes from lab with {total_interfaces} total interfaces")
        return inventory
    except Exception as e:
        logger.error(f"Failed to retrieve lab inventory: {str(e)}")
        sys.exit(1)


def map_macs_to_host_interfaces() -> Dict[str, str]:
    """Get all interfaces on the host and map them to their MAC addresses"""
    logger.info("Mapping MACs to host interfaces")
    try:
        # Get all interfaces and their MACs from the host
        result = subprocess.run(['ip', 'link'], capture_output=True, text=True)
        
        # Parse the output to build a mapping of MAC to interface name
        mac_to_interface = {}
        current_interface = None
        
        for line in result.stdout.splitlines():
            if ': ' in line:  # Line with interface name
                current_interface = line.split(': ')[1].split('@')[0]
            elif 'link/ether' in line and current_interface:  # Line with MAC address
                mac = line.split()[1].lower()
                mac_to_interface[mac] = current_interface
        
        logger.info(f"Found {len(mac_to_interface)} interfaces with MAC addresses")
        return mac_to_interface
    except Exception as e:
        logger.error(f"Failed to map MACs to host interfaces: {str(e)}")
        sys.exit(1)


def map_lab_to_host_interfaces(inventory: Dict, mac_to_interface: Dict[str, str]) -> Dict:
    """Create a mapping from EVE-NG nodes/interfaces to host interfaces"""
    logger.info("Mapping lab interfaces to host interfaces")
    
    # Since we don't have MAC addresses in our EVE-NG interface data,
    # we can't automatically map to host interfaces. Instead, we'll
    # create a structure that allows the user to manually specify
    # the mappings later.
    
    # Debug info about host interfaces
    logger.debug("=== DEBUG: Available Host Interfaces ===")
    sample_host_macs = list(mac_to_interface.keys())[:10]  # Show first 10 host interfaces
    for mac in sample_host_macs:
        logger.debug(f"  Host Interface: {mac_to_interface[mac]} (MAC: {mac})")
    
    # Create a mapping from node/interface to host interface (initially empty)
    node_to_host_interface = {}
    
    for node_id, node_data in inventory.items():
        node_name = node_data['name']
        node_to_host_interface[node_name] = {}
        
        for if_index, if_data in node_data['interfaces'].items():
            if_name = if_data['name']
            # Initially, all mappings are None (not mapped)
            node_to_host_interface[node_name][if_name] = None
    
    # We know we can't map automatically, so mapped_count will be 0
    logger.info(f"Successfully mapped 0 interfaces to host interfaces automatically")
    logger.info(f"You'll need to manually specify interface mappings or use direct interface control")
    
    return node_to_host_interface


def get_bridges_for_interfaces() -> Dict[str, str]:
    """Get the bridge for each interface on the host"""
    logger.info("Getting bridge assignments for interfaces")
    try:
        result = subprocess.run(['brctl', 'show'], capture_output=True, text=True)
        
        # Parse the output to build a mapping of interface to bridge
        interface_to_bridge = {}
        current_bridge = None
        
        for line in result.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 4 and parts[0] != "bridge":  # First line with bridge name
                current_bridge = parts[0]
                if len(parts) > 3:  # If there's an interface on this line
                    interface_to_bridge[parts[3]] = current_bridge
            elif len(parts) == 1 and current_bridge:  # Additional interface for the same bridge
                interface_to_bridge[parts[0]] = current_bridge
        
        logger.info(f"Found {len(interface_to_bridge)} interfaces attached to bridges")
        return interface_to_bridge
    except Exception as e:
        logger.error(f"Failed to get bridges for interfaces: {str(e)}")
        return {}


def suspend_interface(interface_name: str) -> Tuple[bool, str]:
    """Suspend a host interface (bring it down)"""
    logger.info(f"Suspending interface: {interface_name}")
    try:
        subprocess.run(['sudo', 'ip', 'link', 'set', interface_name, 'down'], check=True)
        return True, f"Successfully suspended {interface_name}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to suspend {interface_name}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
        

def suspend_eveng_interface(lab_path: str, device_id: str, interface_id: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Suspend an EVE-NG interface using the unl_wrapper command"""
    logger.info(f"Suspending EVE-NG interface: device {device_id}, interface {interface_id}")
    
    # Construct the command
    cmd = [
        'sudo', '/opt/unetlab/wrappers/unl_wrapper',
        '-a', 'suspendlink',
        '-T', '0',  # Tenant ID, usually 0
        '-I', interface_id,
        '-D', device_id,
        '-F', lab_path
    ]
    
    # In dry run mode, just log the command that would be executed
    if dry_run:
        cmd_str = ' '.join(cmd)
        logger.info(f"DRY RUN - Would execute: {cmd_str}")
        return True, f"DRY RUN - Would suspend device {device_id} interface {interface_id} with command: {cmd_str}"
    
    # Actually execute the command
    try:
        subprocess.run(cmd, check=True)
        return True, f"Successfully suspended device {device_id} interface {interface_id}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to suspend EVE-NG interface: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
        

def suspend_eveng_link(lab_path: str, device1_id: str, interface1_id: str, device2_id: str, interface2_id: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Suspend both sides of an EVE-NG link using the unl_wrapper command"""
    logger.info(f"Suspending EVE-NG link: device {device1_id} interface {interface1_id} <-> device {device2_id} interface {interface2_id}")
    
    # Suspend first side of the link
    success1, message1 = suspend_eveng_interface(lab_path, device1_id, interface1_id, dry_run=dry_run)
    
    # Suspend second side of the link
    success2, message2 = suspend_eveng_interface(lab_path, device2_id, interface2_id, dry_run=dry_run)
    
    if success1 and success2:
        return True, f"Successfully suspended link between device {device1_id} interface {interface1_id} and device {device2_id} interface {interface2_id}"
    elif not success1:
        return False, f"Failed to suspend first side of link: {message1}"
    else:
        return False, f"Failed to suspend second side of link: {message2}"


def resume_interface(interface_name: str) -> Tuple[bool, str]:
    """Resume a host interface (bring it up)"""
    logger.info(f"Resuming interface: {interface_name}")
    try:
        subprocess.run(['sudo', 'ip', 'link', 'set', interface_name, 'up'], check=True)
        return True, f"Successfully resumed {interface_name}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to resume {interface_name}: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
        

def resume_eveng_interface(lab_path: str, device_id: str, interface_id: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Resume an EVE-NG interface using the unl_wrapper command"""
    logger.info(f"Resuming EVE-NG interface: device {device_id}, interface {interface_id}")
    
    # Construct the command
    cmd = [
        'sudo', '/opt/unetlab/wrappers/unl_wrapper',
        '-a', 'resumelink',
        '-T', '0',  # Tenant ID, usually 0
        '-I', interface_id,
        '-D', device_id,
        '-F', lab_path
    ]
    
    # In dry run mode, just log the command that would be executed
    if dry_run:
        cmd_str = ' '.join(cmd)
        logger.info(f"DRY RUN - Would execute: {cmd_str}")
        return True, f"DRY RUN - Would resume device {device_id} interface {interface_id} with command: {cmd_str}"
    
    # Actually execute the command
    try:
        subprocess.run(cmd, check=True)
        return True, f"Successfully resumed device {device_id} interface {interface_id}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to resume EVE-NG interface: {str(e)}"
        logger.error(error_msg)
        return False, error_msg
        

def resume_eveng_link(lab_path: str, device1_id: str, interface1_id: str, device2_id: str, interface2_id: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Resume both sides of an EVE-NG link using the unl_wrapper command"""
    logger.info(f"Resuming EVE-NG link: device {device1_id} interface {interface1_id} <-> device {device2_id} interface {interface2_id}")
    
    # Resume first side of the link
    success1, message1 = resume_eveng_interface(lab_path, device1_id, interface1_id, dry_run=dry_run)
    
    # Resume second side of the link
    success2, message2 = resume_eveng_interface(lab_path, device2_id, interface2_id, dry_run=dry_run)
    
    if success1 and success2:
        return True, f"Successfully resumed link between device {device1_id} interface {interface1_id} and device {device2_id} interface {interface2_id}"
    elif not success1:
        return False, f"Failed to resume first side of link: {message1}"
    else:
        return False, f"Failed to resume second side of link: {message2}"


def remove_from_bridge(bridge_name: str, interface_name: str) -> Tuple[bool, str]:
    """Remove an interface from a bridge"""
    logger.info(f"Removing {interface_name} from bridge {bridge_name}")
    try:
        subprocess.run(['sudo', 'brctl', 'delif', bridge_name, interface_name], check=True)
        return True, f"Successfully removed {interface_name} from {bridge_name}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to remove from bridge: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def add_to_bridge(bridge_name: str, interface_name: str) -> Tuple[bool, str]:
    """Add an interface back to a bridge"""
    logger.info(f"Adding {interface_name} to bridge {bridge_name}")
    try:
        subprocess.run(['sudo', 'brctl', 'addif', bridge_name, interface_name], check=True)
        return True, f"Successfully added {interface_name} to {bridge_name}"
    except subprocess.CalledProcessError as e:
        error_msg = f"Failed to add to bridge: {str(e)}"
        logger.error(error_msg)
        return False, error_msg


def save_mapping(mapping: Dict, filename: str) -> None:
    """Save interface mapping to a file for later use"""
    logger.info(f"Saving mapping to {filename}")
    try:
        with open(filename, 'w') as f:
            json.dump(mapping, f, indent=2)
        logger.info(f"Successfully saved mapping to {filename}")
    except Exception as e:
        logger.error(f"Failed to save mapping: {str(e)}")


def load_mapping(filename: str) -> Optional[Dict]:
    """Load interface mapping from a file"""
    logger.info(f"Loading mapping from {filename}")
    try:
        with open(filename, 'r') as f:
            mapping = json.load(f)
        logger.info(f"Successfully loaded mapping from {filename}")
        return mapping
    except Exception as e:
        logger.error(f"Failed to load mapping: {str(e)}")
        return None


def flap_interface(interface_name: str, count: int = 1, delay: float = 1.0) -> Tuple[bool, str]:
    """Flap an interface (down then up) multiple times"""
    logger.info(f"Flapping interface {interface_name} {count} times with {delay}s delay")
    
    for i in range(count):
        logger.info(f"Flap {i+1}/{count}")
        
        suspend_success, _ = suspend_interface(interface_name)
        if not suspend_success:
            return False, f"Failed to flap {interface_name} (suspend failed)"
        
        time.sleep(delay)
        
        resume_success, _ = resume_interface(interface_name)
        if not resume_success:
            return False, f"Failed to flap {interface_name} (resume failed)"
        
        if i < count - 1:  # Don't sleep after the last iteration
            time.sleep(delay)
    
    return True, f"Successfully flapped {interface_name} {count} times"


def flap_eveng_interface(lab_path: str, device_id: str, interface_id: str, count: int = 1, delay: float = 1.0, dry_run: bool = False) -> Tuple[bool, str]:
    """Flap an EVE-NG interface (suspend then resume) multiple times"""
    logger.info(f"Flapping EVE-NG interface: device {device_id}, interface {interface_id}, {count} times with {delay}s delay")
    
    for i in range(count):
        logger.info(f"Flap {i+1}/{count}")
        
        # Suspend the interface
        suspend_success, suspend_msg = suspend_eveng_interface(lab_path, device_id, interface_id, dry_run)
        if not suspend_success:
            return False, f"Failed to flap device {device_id} interface {interface_id} (suspend failed): {suspend_msg}"
        
        time.sleep(delay)
        
        # Resume the interface
        resume_success, resume_msg = resume_eveng_interface(lab_path, device_id, interface_id, dry_run)
        if not resume_success:
            return False, f"Failed to flap device {device_id} interface {interface_id} (resume failed): {resume_msg}"
        
        if i < count - 1:  # Don't sleep after the last iteration
            time.sleep(delay)
    
    if dry_run:
        return True, f"DRY RUN - Would flap device {device_id} interface {interface_id} {count} times with {delay}s delay"
    else:
        return True, f"Successfully flapped device {device_id} interface {interface_id} {count} times with {delay}s delay"


def get_device_id_by_name(eve_client: EvengClient, lab_path: str, device_name: str) -> Optional[str]:
    """Get the device ID for a device name in the lab"""
    try:
        # Process the lab path to match EVE-NG API expectations
        # The EVE-NG API expects the lab path without the /opt/unetlab/labs/ prefix
        # and without the .unl extension
        if lab_path.startswith('/opt/unetlab/labs/'):
            api_lab_path = lab_path[len('/opt/unetlab/labs/'):]  # Remove prefix
        else:
            api_lab_path = lab_path
            
        # Remove .unl extension if present
        if api_lab_path.endswith('.unl'):
            api_lab_path = api_lab_path[:-4]
            
        logger.debug(f"Using API lab path: {api_lab_path}")
        
        # Get all nodes in the lab
        nodes_response = eve_client.api.list_nodes(api_lab_path)
        
        if nodes_response.get('status') != 'success':
            logger.error(f"Failed to get nodes: {nodes_response}")
            return None
            
        nodes = nodes_response.get('data', {})
        
        # Find the node with the matching name
        for node_id, node in nodes.items():
            if node['name'].lower() == device_name.lower():
                return node_id
                
        logger.error(f"Device name '{device_name}' not found in lab")
        return None
    except Exception as e:
        logger.error(f"Error getting device ID for name '{device_name}': {str(e)}")
        return None


def get_interface_id_by_name(eve_client: EvengClient, lab_path: str, device_id: str, interface_name: str) -> Optional[str]:
    """Get the interface ID for an interface name on a device"""
    try:
        # Process the lab path to match EVE-NG API expectations
        # The EVE-NG API expects the lab path without the /opt/unetlab/labs/ prefix
        # and without the .unl extension
        if lab_path.startswith('/opt/unetlab/labs/'):
            api_lab_path = lab_path[len('/opt/unetlab/labs/'):]  # Remove prefix
        else:
            api_lab_path = lab_path
            
        # Remove .unl extension if present
        if api_lab_path.endswith('.unl'):
            api_lab_path = api_lab_path[:-4]
            
        logger.debug(f"Using API lab path: {api_lab_path}")
        
        # Get interfaces for this node
        interfaces_response = eve_client.api.get_node_interfaces(api_lab_path, device_id)
        
        if interfaces_response.get('status') != 'success':
            logger.error(f"Failed to get interfaces for device {device_id}: {interfaces_response}")
            return None
            
        interfaces = interfaces_response.get('data', {})
        
        # Interface name format is typically like "e0/0" or "Ethernet0/0"
        # We need to parse this and match it to the EVE-NG interface structure
        
        # Common interface patterns: e0/0, eth0, GigabitEthernet0/0, etc.
        interface_type = ''
        interface_number = ''
        
        # Extract type and number from common formats
        if '/' in interface_name:
            parts = interface_name.lower().split('/')
            
            # Extract the type (e, eth, gigabitethernet, etc.)
            type_part = parts[0]
            # Remove any digits from the type part
            interface_type = ''.join([c for c in type_part if not c.isdigit()])
            
            # Extract the type number
            type_number = ''.join([c for c in type_part if c.isdigit()])
            
            # Extract the interface number
            interface_number = parts[1]
            
            # Combine type number and interface number if needed
            if type_number:
                interface_number = f"{type_number}/{interface_number}"
        else:
            # Handle formats like eth0, e0
            for i, c in enumerate(interface_name.lower()):
                if c.isdigit():
                    interface_type = interface_name[:i].lower()
                    interface_number = interface_name[i:]
                    break
        
        # Map common interface type names to EVE-NG types
        eve_types = {
            'e': 'ethernet',
            'eth': 'ethernet',
            'ethernet': 'ethernet',
            'gi': 'ethernet',
            'fa': 'ethernet',
            'g': 'ethernet',
            'gigabitethernet': 'ethernet',
            'fastethernet': 'ethernet',
            's': 'serial',
            'serial': 'serial'
        }
        
        eve_type = eve_types.get(interface_type, 'ethernet')  # Default to ethernet
        
        # Look for the interface in the EVE-NG interface structure
        if eve_type in interfaces:
            # In EVE-NG, interface IDs are often just numbers (0, 1, 2, etc.)
            # Extract the last number from our interface_number
            if '/' in interface_number:
                last_part = interface_number.split('/')[-1]
            else:
                last_part = interface_number
                
            # Find the interface with matching name or ID
            for if_id, if_data in interfaces[eve_type].items():
                # Try to match by ID directly
                if if_id == last_part:
                    return if_id
                    
                # Try to match by name
                if isinstance(if_data, dict) and if_data.get('name', '').lower() == interface_name.lower():
                    return if_id
                    
                # Try to match by partial name (e.g., "e0/0" might match "Ethernet0/0")
                if isinstance(if_data, dict) and interface_name.lower() in if_data.get('name', '').lower():
                    return if_id
        
        logger.error(f"Interface name '{interface_name}' not found on device {device_id}")
        return None
    except Exception as e:
        logger.error(f"Error getting interface ID for name '{interface_name}' on device {device_id}: {str(e)}")
        return None


def suspend_interface_by_name(eve_client: EvengClient, lab_path: str, device_name: str, interface_name: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Suspend an EVE-NG interface using device and interface names"""
    # Get device ID
    device_id = get_device_id_by_name(eve_client, lab_path, device_name)
    if not device_id:
        return False, f"Failed to find device named '{device_name}'"
    
    # Get interface ID
    interface_id = get_interface_id_by_name(eve_client, lab_path, device_id, interface_name)
    if not interface_id:
        return False, f"Failed to find interface named '{interface_name}' on device '{device_name}'"
    
    # Suspend the interface
    return suspend_eveng_interface(lab_path, device_id, interface_id, dry_run=dry_run)


def resume_interface_by_name(eve_client: EvengClient, lab_path: str, device_name: str, interface_name: str, dry_run: bool = False) -> Tuple[bool, str]:
    """Resume an EVE-NG interface using device and interface names"""
    # Get device ID
    device_id = get_device_id_by_name(eve_client, lab_path, device_name)
    if not device_id:
        return False, f"Failed to find device named '{device_name}'"
    
    # Get interface ID
    interface_id = get_interface_id_by_name(eve_client, lab_path, device_id, interface_name)
    if not interface_id:
        return False, f"Failed to find interface named '{interface_name}' on device '{device_name}'"
    
    # Resume the interface
    return resume_eveng_interface(lab_path, device_id, interface_id, dry_run=dry_run)


def process_batch_file(filename: str, operation: str, lab_path: str, dry_run: bool = False, count: int = 1, delay: float = 1.0) -> Tuple[int, int]:
    """
    Process a batch file containing links to suspend, resume, or flap
    
    The file can have two formats:
    1. device1_id,interface1_id,device2_id,interface2_id
    2. device_name,interface_name
    
    Returns a tuple of (success_count, failure_count)
    """
    if not os.path.exists(filename):
        logger.error(f"Batch file not found: {filename}")
        return 0, 0
        
    if operation not in ['suspend', 'resume', 'flap']:
        logger.error(f"Invalid operation: {operation}. Must be 'suspend', 'resume', or 'flap'")
        return 0, 0
        
    success_count = 0
    failure_count = 0
    
    # Get EVE-NG client for device/interface name lookups
    env_host = os.getenv('EVE_HOST')
    env_username = os.getenv('EVE_USERNAME')
    env_password = os.getenv('EVE_PASSWORD')
    
    # Use environment variables if provided
    host = env_host or "localhost"
    username = env_username or "admin"
    password = env_password or "eve"
    
    # Connect to EVE-NG (only needed for name lookups)
    eve_client = connect_to_eveng(host, username, password)
    
    with open(filename, 'r') as f:
        for i, line in enumerate(f, 1):  # Start line counting at 1
            # Skip empty lines and comments
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            try:
                # Try to parse as device1_id,interface1_id,device2_id,interface2_id
                parts = line.split(',')
                
                if len(parts) == 4:  # Full format with device/interface IDs
                    device1_id, interface1_id, device2_id, interface2_id = parts
                    
                    # Execute the operation
                    if operation == 'suspend':
                        result, message = suspend_eveng_link(
                            lab_path, device1_id, interface1_id, device2_id, interface2_id, dry_run
                        )
                    elif operation == 'resume':
                        result, message = resume_eveng_link(
                            lab_path, device1_id, interface1_id, device2_id, interface2_id, dry_run
                        )
                    else:  # operation == 'flap'
                        # For flap on a link, we'll suspend and then resume each side individually
                        # First side
                        result1, message1 = flap_eveng_interface(
                            lab_path, device1_id, interface1_id, count, delay, dry_run
                        )
                        # Second side
                        result2, message2 = flap_eveng_interface(
                            lab_path, device2_id, interface2_id, count, delay, dry_run
                        )
                        result = result1 and result2
                        message = f"Flapped link between device {device1_id} interface {interface1_id} and device {device2_id} interface {interface2_id}"
                        
                    if result:
                        success_count += 1
                        print(f"Line {i}: {message} (for {line})")
                    else:
                        failure_count += 1
                        print(f"Line {i}: Failed - {message} (for {line})")
                        
                elif len(parts) == 2:  # Simplified format with device/interface names
                    device_name, interface_name = parts
                    
                    # Look up device ID by name
                    device_id = get_device_id_by_name(eve_client, lab_path, device_name)
                    if not device_id:
                        failure_count += 1
                        print(f"Line {i}: Failed to find device named '{device_name}' (for {line})")
                        continue
                        
                    # Look up interface ID by name
                    interface_id = get_interface_id_by_name(eve_client, lab_path, device_id, interface_name)
                    if not interface_id:
                        failure_count += 1
                        print(f"Line {i}: Failed to find interface named '{interface_name}' on device {device_name} (for {line})")
                        continue
                    
                    # Execute the operation
                    if operation == 'suspend':
                        result, message = suspend_eveng_interface(
                            lab_path, device_id, interface_id, dry_run
                        )
                    elif operation == 'resume':
                        result, message = resume_eveng_interface(
                            lab_path, device_id, interface_id, dry_run
                        )
                    else:  # operation == 'flap'
                        result, message = flap_eveng_interface(
                            lab_path, device_id, interface_id, count, delay, dry_run
                        )
                        
                    if result:
                        success_count += 1
                        print(f"Line {i}: {message} (for {line})")
                    else:
                        failure_count += 1
                        print(f"Line {i}: Failed - {message} (for {line})")
                else:
                    failure_count += 1
                    print(f"Line {i}: Invalid format - expected 2 or 4 comma-separated values, got {len(parts)} (for {line})")
            except Exception as e:
                failure_count += 1
                print(f"Line {i}: Error processing line: {str(e)} (for {line})")
                
    return success_count, failure_count


def main():
    parser = argparse.ArgumentParser(description='EVE-NG Link Manager for LogZilla Demos')
    
    # Connection parameters
    parser.add_argument('--host', help='EVE-NG server URL (https://your-eve-ng-server)')
    parser.add_argument('--username', help='EVE-NG username')
    parser.add_argument('--password', help='EVE-NG password')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    
    subparsers = parser.add_subparsers(dest='command', help='Command to run')
    
    # Inventory command
    inventory_parser = subparsers.add_parser('inventory', help='Get inventory of EVE-NG lab')
    inventory_parser.add_argument('--lab', help='EVE-NG lab path (relative to /opt/unetlab/labs/)')
    
    # Suspend command
    suspend_parser = subparsers.add_parser('suspend', help='Suspend an interface or link')
    suspend_parser.add_argument('--interface', help='Host interface name to suspend')
    suspend_parser.add_argument('--device-id', help='EVE-NG device ID to suspend interface on')
    suspend_parser.add_argument('--interface-id', help='EVE-NG interface ID to suspend')
    suspend_parser.add_argument('--lab', help='EVE-NG lab path (required for EVE-NG operations)')
    suspend_parser.add_argument('--device1-id', help='First EVE-NG device ID for link suspension')
    suspend_parser.add_argument('--interface1-id', help='First EVE-NG interface ID for link suspension')
    suspend_parser.add_argument('--device2-id', help='Second EVE-NG device ID for link suspension')
    suspend_parser.add_argument('--interface2-id', help='Second EVE-NG interface ID for link suspension')
    suspend_parser.add_argument('--dry-run', action='store_true', help='Only log what would be done, without actually suspending links')
    
    # Resume command
    resume_parser = subparsers.add_parser('resume', help='Resume an interface or link')
    resume_parser.add_argument('--interface', help='Host interface name to resume')
    resume_parser.add_argument('--device-id', help='EVE-NG device ID to resume interface on')
    resume_parser.add_argument('--interface-id', help='EVE-NG interface ID to resume')
    resume_parser.add_argument('--lab', help='EVE-NG lab path (required for EVE-NG operations)')
    resume_parser.add_argument('--device1-id', help='First EVE-NG device ID for link resumption')
    resume_parser.add_argument('--interface1-id', help='First EVE-NG interface ID for link resumption')
    resume_parser.add_argument('--device2-id', help='Second EVE-NG device ID for link resumption')
    resume_parser.add_argument('--interface2-id', help='Second EVE-NG interface ID for link resumption')
    resume_parser.add_argument('--dry-run', action='store_true', help='Only log what would be done, without actually resuming links')
    
    # Flap command
    flap_parser = subparsers.add_parser('flap', help='Flap (suspend then resume) an interface')
    flap_parser.add_argument('--interface', help='Host interface name to flap')
    flap_parser.add_argument('--device-id', help='EVE-NG device ID to flap interface on')
    flap_parser.add_argument('--interface-id', help='EVE-NG interface ID to flap')
    flap_parser.add_argument('--lab', help='EVE-NG lab path (required for EVE-NG operations)')
    flap_parser.add_argument('--count', type=int, default=1, help='Number of times to flap the interface')
    flap_parser.add_argument('--delay', type=float, default=1.0, help='Delay in seconds between suspend and resume')
    flap_parser.add_argument('--dry-run', action='store_true', help='Only log what would be done, without actually flapping links')
    
    # Batch command
    batch_parser = subparsers.add_parser('batch', help='Process multiple links from a file')
    batch_parser.add_argument('--operation', choices=['suspend', 'resume', 'flap'], required=True, help='Operation to perform on the links')
    batch_parser.add_argument('--file', required=True, help='File containing links to process, one per line in format:\ndevice1_id,interface1_id,device2_id,interface2_id')
    batch_parser.add_argument('--lab', required=True, help='EVE-NG lab path (required for batch operations)')
    batch_parser.add_argument('--count', type=int, default=1, help='Number of times to flap each interface (only used with flap operation)')
    batch_parser.add_argument('--delay', type=float, default=1.0, help='Delay in seconds between suspend and resume (only used with flap operation)')
    batch_parser.add_argument('--dry-run', action='store_true', help='Only log what would be done, without actually performing operations')
    
    args = parser.parse_args()
    
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Load from default .env file if it exists
    if os.path.exists('.env'):
        load_dotenv()
        logger.info("Loaded environment variables from .env")
    
    # Get lab path from args or environment
    lab_path = args.lab or os.getenv('EVE_LAB')
    if not lab_path and (args.command in ['suspend', 'resume', 'flap'] and args.use_eveng_api):
        lab_path = input("Path to lab file: ")
    
    # If lab path doesn't start with /opt/unetlab/labs, add it
    if lab_path and not lab_path.startswith('/opt/unetlab/labs'):
        lab_path = f"/opt/unetlab/labs/{lab_path}"
    
    # Initialize node_to_host_interface for operations that need it
    node_to_host_interface = {}
    
    # Handle commands based on the selected subcommand
    if args.command == 'inventory':
        # Get EVE-NG connection details from environment variables or prompt
        host = os.getenv('EVE_HOST')
        username = os.getenv('EVE_USERNAME')
        password = os.getenv('EVE_PASSWORD')
        
        # Prompt for missing details if needed
        if not host:
            host = input("EVE-NG server URL: ")
        if not username:
            username = input("EVE-NG username: ")
        if not password:
            password = getpass("EVE-NG password: ")
        if not lab_path:
            lab_path = input("Path to lab file: ")
        
        # Connect to EVE-NG and get inventory
        client = connect_to_eveng(host, username, password)
        inventory = get_lab_inventory(client, lab_path)
        
        # Map MACs to host interfaces
        mac_to_interface = map_macs_to_host_interfaces()
        
        # Map lab interfaces to host interfaces
        node_to_host_interface = map_lab_to_host_interfaces(inventory, mac_to_interface)
        
        # Print the inventory
        print(json.dumps(node_to_host_interface, indent=2))
        
        # Also print in a more human-readable format
        for node_name, interfaces in node_to_host_interface.items():
            print(f"Node: {node_name}")
            for if_name, host_if in interfaces.items():
                print(f"  Interface: {if_name}, Host Interface: {host_if}")
    
    elif args.command == 'suspend':
        # Handle dry run mode
        dry_run = args.dry_run if hasattr(args, 'dry_run') else False
        
        if args.device1_id and args.interface1_id and args.device2_id and args.interface2_id:
            # Use link operation to suspend both sides of a link
            success, message = suspend_eveng_link(
                lab_path, args.device1_id, args.interface1_id, args.device2_id, args.interface2_id, dry_run=dry_run
            )
            print(message)
        elif args.device_id and args.interface_id:
            # Use direct EVE-NG API control for a single interface
            success, message = suspend_eveng_interface(lab_path, args.device_id, args.interface_id, dry_run=dry_run)
            print(message)
        elif args.interface:
            # Suspend host interface directly
            success, message = suspend_interface(args.interface)
            print(message)
        # Legacy node/interface mapping has been removed
        else:
            print("Error: Either --interface, or --device-id and --interface-id, or --device1-id, --interface1-id, --device2-id, --interface2-id must be specified")
    
    elif args.command == 'resume':
        # Handle dry run mode
        dry_run = args.dry_run if hasattr(args, 'dry_run') else False
        
        if args.device1_id and args.interface1_id and args.device2_id and args.interface2_id:
            # Use link operation to resume both sides of a link
            success, message = resume_eveng_link(
                lab_path, args.device1_id, args.interface1_id, args.device2_id, args.interface2_id, dry_run=dry_run
            )
            print(message)
        elif args.device_id and args.interface_id:
            # Use direct EVE-NG API control for a single interface
            success, message = resume_eveng_interface(lab_path, args.device_id, args.interface_id, dry_run=dry_run)
            print(message)
        elif args.interface:
            # Resume host interface directly
            success, message = resume_interface(args.interface)
            print(message)
        # Legacy node/interface mapping has been removed
        else:
            print("Error: Either --interface, or --device-id and --interface-id, or --device1-id, --interface1-id, --device2-id, --interface2-id must be specified")
    
    elif args.command == 'flap':
        # Handle dry run mode
        dry_run = args.dry_run if hasattr(args, 'dry_run') else False
        count = args.count if hasattr(args, 'count') else 1
        delay = args.delay if hasattr(args, 'delay') else 1.0
        
        if args.device_id and args.interface_id:
            # Use direct EVE-NG API control for a single interface
            success, message = flap_eveng_interface(
                lab_path, args.device_id, args.interface_id, count=count, delay=delay, dry_run=dry_run
            )
            print(message)
        elif args.interface:
            # Flap host interface directly
            success, message = flap_interface(args.interface, count=count, delay=delay)
            print(message)
        else:
            print("Error: Either --interface, or --device-id and --interface-id must be specified")
            
    elif args.command == 'batch':
        # Ensure lab path is properly formed
        if args.lab and not args.lab.startswith('/opt/unetlab/labs'):
            lab_path = f"/opt/unetlab/labs/{args.lab}"
        else:
            lab_path = args.lab
            
        # Get count and delay for flap operations
        count = args.count if hasattr(args, 'count') else 1
        delay = args.delay if hasattr(args, 'delay') else 1.0
            
        # Process batch file
        success_count, failure_count = process_batch_file(
            args.file, args.operation, lab_path, dry_run=args.dry_run,
            count=count, delay=delay
        )
        
        # Print summary
        print(f"\nBatch processing complete:")
        print(f"  Successful operations: {success_count}")
        print(f"  Failed operations: {failure_count}")
        
        if failure_count > 0:
            return 1  # Return non-zero exit code if any operations failed


if __name__ == "__main__":
    main()
