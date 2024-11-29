import json
import csv
from .base import base_benches, Bench, DeviceScheduler, spdk_bdev
from benchs.base import is_dev_zoned, spdk_build

class ConfigParser:
    def __init__(self, obj):
        # Initialize default values or leave empty
        self.obj = obj

    def parse_and_set(self, kv_string):
        # Split on the '=' character to separate key and value
        key, value = kv_string.split('=')

        # Set the instance attribute dynamically
        setattr(self.obj, key, value)

class Run(Bench):
    jobname = "fio_zone_mixed_args"
    blocksize_writes = "64k"
    blocksize_reads = "4k"
    max_open_zones = 14
    write_iolog = "0"
    numjobs = "1"

    def __init__(self):
        pass

    def get_default_device_scheduler(self):
        return DeviceScheduler.NONE

    def id(self):
        return self.jobname

    def setup(self, dev, container, output, arguments):
        super(Run, self).setup(container, output, arguments)

        config = ConfigParser(self)

        for v in arguments:
            config.parse_and_set(v)

        print("ARGS: ", self.arguments)
        print("ARGS (set): ", vars(self))

        self.discard_dev(dev)

    def required_container_tools(self):
        return super().required_container_tools() | {'fio'}

    def run(self, dev, container):
        extra = ''

        if is_dev_zoned(dev):
            # Zone Capacity (52% of zone size)
            zonecap = 52
        else:
            # Zone Size = Zone Capacity on a conv. drive
            zonecap = 100
            extra = '--zonesize=1102848k'

        io_size = int(((self.get_dev_size(dev) * zonecap) / 100) * 2)

        if self.spdk_path:
           # SPDK specific args
            extra = extra + f" --ioengine={self.spdk_path}/spdk/build/fio/spdk_bdev --spdk_json_conf={self.spdk_path}/spdk/bdev_zoned_uring.json --thread=1 "
            if container == 'no':
                #Checkout and build SPDK for Host system
                spdk_build("spdk/uring", self.spdk_path, dev)

                # Replace the nvme physical dev with spdk bdev.
                # For '-c yes' case, we pass the nvme dev to the container and
                # then replace it within the spdk bdev
                dev = spdk_bdev
        else:
            extra = extra + ' --ioengine=io_uring '

        init_param = (f" --direct=1"
                      f" --zonemode=zbd"
                      f" --output-format=json"
                      f" --max_open_zones={self.max_open_zones}"
                      f" --filename={dev}"
                      f" --rw=randwrite"
                      f" --norandommap"
                      f" --bs={self.blocksize_writes}"
                      f" {extra}")

        prep_param = (f"--name=prep"
                      f" --io_size={io_size}k"
                      f" --output {self.result_path()}/{self.jobname}.log")

        mixs_param = ("--name=mix_0_r"
                      " --wait_for_previous"
                      " --rw=randread"
                      " --norandommap"
                      f" --bs={self.blocksize_reads}"
                      " --runtime=180"
                      " --ramp_time=30"
                      " --time_based"
                      " --significant_figures=6"
                      " --percentile_list=1:5:10:20:30:40:50:60:70:80:90:99:99.9:99.99:99.999:99.9999:99.99999:100")
        if self.write_iolog == "1":
            mixs_param += f" --write_iolog={self.result_path()}/write_iolog_0r.txt"
        if self.numjobs != "1":
            mixs_param += f" --numjobs={self.numjobs}"
        for s in [25, 50, 75, 100, 125, 150, 175, 200, 300, 400, 500, 600, 700, 800, 900, 1000]:
            mixs_param += (f" --name=mix_{s}_w"
                           f" --wait_for_previous"
                           f" --rate={s}m"
                           f" --bs={self.blocksize_writes}"
                           f" --runtime=180"
                           f" --time_based")
            if self.write_iolog == "1":
                mixs_param += f" --write_iolog={self.result_path()}/write_iolog_{s}w.txt"
            if self.numjobs != "1":
                mixs_param += f" --numjobs={self.numjobs}"

            mixs_param += (f" --name=mix_{s}_r"
                           f" --rw=randread"
                           f" --norandommap"
                           f" --bs={self.blocksize_reads}"
                           f" --runtime=180"
                           f" --ramp_time=30"
                           f" --time_based"
                           f" --significant_figures=6"
                           f" --percentile_list=1:5:10:20:30:40:50:60:70:80:90:99:99.9:99.99:99.999:99.9999:99.99999:100")
            if self.write_iolog == "1":
                mixs_param += f" --write_iolog={self.result_path()}/write_iolog_{s}r.txt"
            if self.numjobs != "1":
                mixs_param += f" --numjobs={self.numjobs}"

        fio_param = f"{init_param} {prep_param} {mixs_param}"

        self.run_cmd(dev, container, 'fio', fio_param)

    def teardown(self, dev, container):
        pass

    def report(self, path):

        csv_data = []
        with open(path + "/" + self.jobname + ".log", 'r') as f:
            data = json.load(f)

        write_avg = 0
        for job in data['jobs']:
            if "prep" in job['jobname']:
                continue

            if "w" in job['jobname']:
                write_avg = int(int(job['write']['bw_mean']) / 1024)
                continue

            write_target = int(job['jobname'].strip("mix_").strip("_r"))
            lat_us = "%0.3f" % float(job['read']['lat_ns']['mean'] / 1000)
            p = []
            p.append(int(job['read']['bw']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['1.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['5.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['10.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['20.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['30.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['40.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['50.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['60.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['70.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['80.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['90.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.000000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.900000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.990000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.999000']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.999900']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['99.999990']) / 1000)
            p.append(int(job['read']['clat_ns']['percentile']['100.000000']) / 1000)

            lat_reported = ''
            if write_target == write_avg:
                lat_reported = lat_us

            t = [write_target, lat_reported, write_avg, lat_us]
            t.extend(p)

            csv_data.append(t)

        csv_file = path + "/" + self.jobname + ".csv"
        with open(csv_file, 'w') as f:
            w = csv.writer(f, delimiter=',')
            w.writerow(['write_avg_mbs_target', 'read_lat_avg_us', 'write_avg_mbs', 'read_lat_avg_us_measured', 'read_avg_mbs', \
                        'clat_p1_us','clat_p5_us', 'clat_p10_us', 'clat_p20_us', 'clat_p30_us', 'clat_p40_us', \
                        'clat_p50_us','clat_p60_us','clat_p70_us','clat_p80_us', \
                        'clat_p90_us', 'clat_p99_us','clat_p99.9_us','clat_p99.99_us', 'clat_p99.999_us', \
                        'clat_p99.9999_us', 'clat_p99.99999_us', 'clat_max_us'])
            w.writerows(csv_data)

        print(f"  Output written to: {csv_file}")
        return csv_file


base_benches.append(Run())
