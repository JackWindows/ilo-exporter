#!/usr/bin/env python
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
            for key, value in embedded_health['health_at_a_glance'].items():
                gauge_name = f'hpilo_health_at_a_glance_{key}'
                gauge_documentation = f'iLO health at a glance status for {key}, ' \
                                      '0: Unknown, 1: OK, 2: Degraded, 3: Failed.'
                status = value['status'].lower()
                gauge_value = 0
                if status == 'ok':
                    gauge_value = 1
                elif status == 'degraded':
                    gauge_value = 2
                elif status == 'failed':
                    gauge_value = 3
                g = GaugeMetricFamily(gauge_name, gauge_documentation, labels=label_names)
                g.add_metric(label_values, gauge_value)
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
            for sensor in embedded_health['temperature'].values():
                if sensor['currentreading'] == 'N/A':
                    continue
                canonicalized_sensor_name = sensor['label'].lower() \
                                                           .replace(' ', '_').replace('-', '_').replace('/', '')
                gauge_name = f'hpilo_temperature_{canonicalized_sensor_name}'
                gauge_documentation = f'Temperature reading for {sensor["label"]} in {sensor["currentreading"][1]}.'
                gauge_value = sensor['currentreading'][0]
                gauge_unit = sensor['currentreading'][1].lower()
                g = GaugeMetricFamily(gauge_name, gauge_documentation, labels=label_names, unit=gauge_unit)
                g.add_metric(label_values, gauge_value)
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
