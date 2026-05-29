import logging
import os
import platform
import subprocess
import time

from desktop_env.providers.base import Provider

logger = logging.getLogger("desktopenv.providers.vmware.VMwareProvider")
logger.setLevel(logging.INFO)

WAIT_TIME = 3
STOP_TIMEOUT = 60
POST_STOP_WAIT_TIME = 3


def get_vmrun_type(return_list=False):
    if platform.system() == 'Windows' or platform.system() == 'Linux':
        if return_list:
            return ['-T', 'ws']
        else:
            return '-T ws'
    elif platform.system() == 'Darwin':  # Darwin is the system name for macOS
        if return_list:
            return ['-T', 'fusion']
        else:
            return '-T fusion'
    else:
        raise Exception("Unsupported operating system")


class VMwareProvider(Provider):
    @staticmethod
    def _execute_command(command: list, return_output=False):
        process = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if process.returncode != 0:
            raise subprocess.CalledProcessError(
                process.returncode,
                command,
                output=process.stdout,
                stderr=process.stderr,
            )

        if return_output:
            return process.stdout.strip()
        else:
            return None

    @staticmethod
    def _normalize_vm_path(path_to_vm: str):
        return os.path.abspath(os.path.normpath(path_to_vm))

    @classmethod
    def _list_running_vms(cls):
        output = cls._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["list"],
            return_output=True,
        )
        return output.splitlines()[1:] if output else []

    @classmethod
    def _is_vm_running(cls, path_to_vm: str):
        normalized_path_to_vm = cls._normalize_vm_path(path_to_vm)
        return any(
            cls._normalize_vm_path(line) == normalized_path_to_vm
            for line in cls._list_running_vms()
        )

    @classmethod
    def _wait_until_stopped(cls, path_to_vm: str, timeout=STOP_TIMEOUT):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not cls._is_vm_running(path_to_vm):
                return
            time.sleep(WAIT_TIME)

        raise TimeoutError(
            f"Timed out waiting for VMware VM to stop: {path_to_vm}"
        )

    @classmethod
    def _stop_vm_if_running(cls, path_to_vm: str):
        if not cls._is_vm_running(path_to_vm):
            logger.info("VM is not running.")
            return

        logger.info("VM is running; stopping it before continuing...")
        cls._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["stop", path_to_vm, "hard"]
        )
        cls._wait_until_stopped(path_to_vm)
        # VMware can keep disk locks briefly after vmrun reports the VM stopped.
        time.sleep(POST_STOP_WAIT_TIME)

    def start_emulator(self, path_to_vm: str, headless: bool, os_type: str):
        print("Starting VMware VM...")
        logger.info("Starting VMware VM...")

        while True:
            try:
                if VMwareProvider._is_vm_running(path_to_vm):
                    logger.info("VM is running.")
                    break
                else:
                    logger.info("Starting VM...")
                    _command = ["vmrun"] + get_vmrun_type(return_list=True) + ["start", path_to_vm]
                    if headless:
                        _command.append("nogui")
                    VMwareProvider._execute_command(_command)
                    time.sleep(WAIT_TIME)

            except subprocess.CalledProcessError as e:
                error_output = (e.stderr or e.output or "").strip()
                logger.error(f"Error executing command: {error_output}")
                time.sleep(WAIT_TIME)

    def get_ip_address(self, path_to_vm: str) -> str:
        logger.info("Getting VMware VM IP address...")
        while True:
            try:
                output = VMwareProvider._execute_command(
                    ["vmrun"] + get_vmrun_type(return_list=True) + ["getGuestIPAddress", path_to_vm, "-wait"],
                    return_output=True
                )
                logger.info(f"VMware VM IP address: {output}")
                return output
            except Exception as e:
                logger.error(e)
                time.sleep(WAIT_TIME)
                logger.info("Retrying to get VMware VM IP address...")

    def save_state(self, path_to_vm: str, snapshot_name: str):
        logger.info("Saving VMware VM state...")
        VMwareProvider._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["snapshot", path_to_vm, snapshot_name])
        time.sleep(WAIT_TIME)  # Wait for the VM to save

    def revert_to_snapshot(self, path_to_vm: str, snapshot_name: str):
        logger.info(f"Reverting VMware VM to snapshot: {snapshot_name}...")
        VMwareProvider._stop_vm_if_running(path_to_vm)
        VMwareProvider._execute_command(
            ["vmrun"] + get_vmrun_type(return_list=True) + ["revertToSnapshot", path_to_vm, snapshot_name])
        time.sleep(WAIT_TIME)  # Wait for the VM to revert
        return path_to_vm

    def stop_emulator(self, path_to_vm: str, region=None, *args, **kwargs):
        # Note: region parameter is ignored for VMware provider
        # but kept for interface consistency with other providers
        logger.info("Stopping VMware VM...")
        VMwareProvider._stop_vm_if_running(path_to_vm)
