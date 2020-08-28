#!/usr/bin/env python
import collections
import hpilo
import os
import waitress
from flask import Flask
from prometheus_client import make_wsgi_app
from prometheus_client.core import GaugeMetricFamily, REGISTRY
from werkzeug.middleware.dispatcher import DispatcherMiddleware


class ILOCollector(object):
    def __init__(self, hostname: str, port: int = 443, user: str = 'admin', password: str = 'password',
                 protocol: str = 'HTTP') -> None:
        if protocol == 'HTTP':
            protocol = hpilo.ILO_HTTP
        elif protocol == 'LOCAL':
            protocol = hpilo.ILO_LOCAL
        else:
            raise RuntimeError(f'unsupported protocol {protocol}')
        self.ilo = hpilo.Ilo(hostname=hostname, port=port, login=user, password=password, protocol=protocol)
        self.product_name = self.ilo.get_product_name()
        self.hostname = hostname

    def collect(self):
        embedded_health = self.ilo.get_embedded_health()

        label_names = ('hostname', 'product_name')
        label_values = (self.hostname, self.product_name)

        if embedded_health['health_at_a_glance'] is not None:
            g = GaugeMetricFamily('hpilo_health_at_a_glance',
                                  'iLO health at a glance status, 0: Unknown, 1: OK, 2: Degraded, 3: Failed.',
                                  labels=label_names + ('component',))
            for key, value in embedded_health['health_at_a_glance'].items():
                status = value['status'].lower()
                metric_value = -1
                if status == 'ok':
                    metric_value = 0
                elif status == 'degraded':
                    metric_value = 1
                elif status == 'failed':
                    metric_value = 2
                g.add_metric(label_values + (key,), metric_value)
            yield g

        if embedded_health['fans'] is not None:
            g = GaugeMetricFamily('hpilo_fan_speed', 'Fan speed in percentage.',
                                  labels=label_names + ('fan',), unit='percentage')
            for fan in embedded_health['fans'].values():
                metric_label = label_values + (fan['label'],)
                metric_value = fan['speed'][0]
                g.add_metric(metric_label, metric_value)
            yield g

        if embedded_health['temperature'] is not None:
            sensors_by_unit = collections.defaultdict(list)
            for sensor in embedded_health['temperature'].values():
                if sensor['currentreading'] == 'N/A':
                    continue
                reading, unit = sensor['currentreading']
                sensors_by_unit[unit].append((sensor['label'], reading))
            for unit in sensors_by_unit:
                g = GaugeMetricFamily('hpilo_temperature', 'Temperature sensors reading.',
                                      labels=label_names + ('sensor',), unit=unit.lower())
                for sensor_name, sensor_reading in sensors_by_unit[unit]:
                    g.add_metric(label_values + (sensor_name,), sensor_reading)
                yield g

        if embedded_health['power_supply_summary'] is not None:
            g = GaugeMetricFamily('hpilo_power_reading', 'Power reading in Watts.', labels=label_names, unit='watts')
            gauge_value = int(embedded_health['power_supply_summary']['present_power_reading'].split(' ')[0])
            g.add_metric(label_values, gauge_value)
            yield g


# Create Flask app
app = Flask('iLO Exporter')

# Add prometheus wsgi middleware to route /metrics requests
app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {
    '/metrics': make_wsgi_app()
})


@app.route('/')
def root():
    return '''<html>
<head><title>iLO Exporter</title></head>
<body>
<h1>iLO Exporter</h1>
<p><a href='/metrics'>Metrics</a></p>
</body>
</html>'''


if __name__ == '__main__':
    hostname = os.getenv('ILO_HOST')
    if hostname is None:
        raise RuntimeError('ILO_HOST not set')
    port = int(os.getenv('ILO_PORT', 443))
    user = os.getenv('ILO_USER', 'admin')
    password = os.getenv('ILO_PASSWORD', 'password')
    protocol = os.getenv('ILO_PROTOCOL', 'HTTP')

    collector = ILOCollector(hostname, port, user, password, protocol)
    REGISTRY.register(collector)

    exporter_port = int(os.getenv('LISTEN_PORT', 9116))
    waitress.serve(app, host='0.0.0.0', port=exporter_port)
