# Nova External Scheduler (nova-ext-sched)

`nova-ext-sched` is a Stevedore plugin that extends OpenStack Nova's default scheduling mechanism by enabling the integration of external filters and weighers. This allows enhanced scheduling logic based on external monitoring systems such as Prometheus.

**Status:** Example project — no expected maintenance.

## Overview

Nova's default scheduler uses a filter/weigher model to select compute nodes. This plugin injects external logic into that decision-making process, enabling context-aware decisions such as current system load, custom metrics, and other constraints not handled natively.

The plugin consists of two main parts:

- **Integration hooks in Nova** (`external_filter.py`, `external_weigher.py`): glue code to enable Nova to load external filters/weighers.
- **Plugin logic under `external_scheduler/`**: a Stevedore plugin system where filters/weighers are defined. For example, `cpuload_filter` and `cpuload_weight` rely on Prometheus metrics.

The plugin operates by hooking into Nova's filtering and weighing phases. It first retrieves all necessary monitoring data in one batch before applying custom logic per host.

## Installation

1. **Clone and install the plugin**

```bash
git clone https://your/repository/nova-ext-sched.git
cd nova-ext-sched
/opt/openstack/nova/bin/python3.x -m pip install .
```

Edit `external_scheduler/plugin.conf` before installation to configure the plugin's behavior.

2. **Add the interface glue code to Nova's codebase**

```bash
cp nova/scheduler/filters/external_filter.py ${nova-folder}/nova/scheduler/filters/
cp nova/scheduler/weights/external_weigher.py ${nova-folder}/nova/scheduler/weights/
```

- In /etc/nova/nova.conf, Place ExternalFilter last in the filter chain to minimize monitoring overhead.
- If only filtering is needed, skip the weigh injection (Weighers are applied automatically if ExternalWeigher is present).

3. **Restart the scheduler**

```bash
systemctl restart nova-scheduler.service
```

## Extending

To implement your own filter or weigher:

- Derive from base_filter.BaseFilter or base_weigher.BaseWeigher
- Override the methods to your needs
- Declare the name in filters/weights/__init__.py
- Add the name to `plugin.conf` to enable it

## Test purpose

```bash
sudo iptables -A OUTPUT -p tcp -m tcp --dport 9090 -j REJECT
sudo iptables -D OUTPUT -p tcp -m tcp --dport 9090 -j REJECT
```

## Miscellaneous

Request used to compute the idle ratio prediction :

Without record:

```promql
  quantile_over_time(
    0.01,
(avg by (instance) (rate(node_cpu_seconds_total{instance=~".*host.*",mode="idle"}[5m])))[3d:]
  )
-
    3
  *
    stddev_over_time(
(avg by (instance) (rate(node_cpu_seconds_total{instance=~".*host.*",mode="idle"}[5m])))[3d:]
    )
```

With record:
```promql
rec_host_cpu_idle_q01{instance=~'host*'}
-
    2
  *
rec_host_cpu_idle_std{instance=~'host*'}
```
