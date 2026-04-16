import platform
import subprocess
import sys
import logging

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def detect_hardware():
    """
    Comprehensive hardware profiling for overlay optimization.
    Detects modern and legacy GPUs (NVIDIA, AMD, Intel).
    """
    hw_profile = {
        "os": sys.platform,
        "cpu_arch": platform.machine(),
        "cpu_model": platform.processor(),
        "gpu_vendor": "Generic/Legacy",
        "gpu_model": "Unknown"
    }
    
    try:
        if sys.platform == "win32":
            gpu_info = subprocess.check_output(["wmic", "path", "win32_VideoController", "get", "name"]).decode()
            if "NVIDIA" in gpu_info: hw_profile["gpu_vendor"] = "NVIDIA"
            elif "Intel" in gpu_info: hw_profile["gpu_vendor"] = "Intel"
            elif "AMD" in gpu_info or "Radeon" in gpu_info: hw_profile["gpu_vendor"] = "AMD"
            hw_profile["gpu_model"] = gpu_info.replace("Name", "").strip()
            
        elif sys.platform == "linux":
            # Native Linux hardware detection via lspci
            gpu_info = subprocess.check_output(["lspci"]).decode()
            if "NVIDIA" in gpu_info: hw_profile["gpu_vendor"] = "NVIDIA"
            elif "Intel" in gpu_info: hw_profile["gpu_vendor"] = "Intel"
            elif "AMD" in gpu_info: hw_profile["gpu_vendor"] = "AMD"
            hw_profile["gpu_model"] = "Linux PCI Device (See lspci for details)"
            
    except Exception as e:
        logging.warning(f"Hardware detection failed: {e}. Defaulting to safe render mode.")

    return hw_profile

if __name__ == "__main__":
    profile = detect_hardware()
    logging.info(f"Setup Complete. Hardware Profile: {profile}")