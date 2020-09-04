#!/usr/bin/env python
import collections
import os
import redfish
import waitress
from flask import Flask
from prometheus_client import make_wsgi_app
from prometheus_client.core import GaugeMetricFamily, REGISTRY
from werkzeug.middleware.dispatcher import DispatcherMiddleware


class ILOCollector(object):
    def __init__(self, hostname: str, port: int = 443, user: str = 'admin', password: str = 'password') -> None:
        self.ilo = redfish.LegacyRestClient(base_url=hostname, username=user, password=password)
        self.ilo.login()

        system = self.ilo.get('/redfish/v1/Systems/1/').obj
        self.label_names = ('hostname', 'product_name', 'sn')
        self.label_values = (hostname, system.Model, system.SerialNumber.strip())

    def collect(self):
        embedded_media = self.ilo.get('/redfish/v1/Managers/1/EmbeddedMedia/').obj
        smart_storage = self.ilo.get('/redfish/v1/Systems/1/SmartStorage/').obj
        thermal = self.ilo.get('/redfish/v1/Chassis/1/Thermal/').obj
        power = self.ilo.get('/redfish/v1/Chassis/1/Power/').obj

        g = GaugeMetricFamily('hpilo_health',
                              'iLO health status, -1: Unknown, 0: OK, 1: Degraded, 2: Failed.',
                              labels=self.label_names + ('component',))

        def status_to_code(status: str) -> int:
            status = status.lower()
            ret = -1
            if status == 'ok':
                ret = 0
            elif status == 'warning':
                ret = 1
            elif status == 'failed':
                ret = 2
            return ret

        g.add_metric(self.label_values + ('embedded_media',), status_to_code(embedded_media.Controller.Status.Health))
        g.add_metric(self.label_values + ('smart_storage',), status_to_code(smart_storage.Status.Health))
        for fan in thermal.Fans:
            g.add_metric(self.label_values + (fan.FanName,), status_to_code(fan.Status.Health))
        yield g

        g = GaugeMetricFamily('hpilo_fan_speed', 'Fan speed in percentage.',
                              labels=self.label_names + ('fan',), unit='percentage')
        for fan in thermal.Fans:
            g.add_metric(self.label_values + (fan.FanName,), fan.CurrentReading)
        yield g

        sensors_by_unit = collections.defaultdict(list)
        for sensor in thermal.Temperatures:
            if sensor.Status.State.lower() != 'enabled':
                continue
            reading = sensor.CurrentReading
            unit = sensor.Units
            sensors_by_unit[unit].append((sensor.Name, reading))
        for unit in sensors_by_unit:
            g = GaugeMetricFamily('hpilo_temperature', 'Temperature sensors reading.',
                                  labels=self.label_names + ('sensor',), unit=unit.lower())
            for sensor_name, sensor_reading in sensors_by_unit[unit]:
                g.add_metric(self.label_values + (sensor_name,), sensor_reading)
            yield g

        g = GaugeMetricFamily('hpilo_power_current', 'Current power consumption in Watts.', labels=self.label_names,
                              unit='watts')
        g.add_metric(self.label_values, power.PowerConsumedWatts)
        yield g

        label_values = self.label_values + (str(power.PowerMetrics.IntervalInMin),)
        g = GaugeMetricFamily('hpilo_power_average', 'Average power consumption in Watts.',
                              labels=self.label_names + ('IntervalInMin',), unit='watts')
        g.add_metric(label_values, power.PowerMetrics.AverageConsumedWatts)
        yield g
        g = GaugeMetricFamily('hpilo_power_min', 'Min power consumption in Watts.',
                              labels=self.label_names + ('IntervalInMin',), unit='watts')
        g.add_metric(label_values, power.PowerMetrics.MinConsumedWatts)
        yield g
        g = GaugeMetricFamily('hpilo_power_max', 'Max power consumption in Watts.',
                              labels=self.label_names + ('IntervalInMin',), unit='watts')
        g.add_metric(label_values, power.PowerMetrics.MaxConsumedWatts)
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

    collector = ILOCollector(hostname, port, user, password)
    REGISTRY.register(collector)

    exporter_port = int(os.getenv('LISTEN_PORT', 9116))
    waitress.serve(app, host='0.0.0.0', port=exporter_port)
