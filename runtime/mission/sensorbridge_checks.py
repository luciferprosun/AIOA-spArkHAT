"""Registered checks for the public fixture, executed only in the sandbox."""
import importlib.util
import io
import sys
import unittest

spec = importlib.util.spec_from_file_location('sensorbridge', '/work/project/sensorbridge.py')
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class SensorTests(unittest.TestCase):
    def test_first_sample(self):
        self.assertEqual({'sequence': 0, 'temperature_c': 20.0, 'humidity_pct': 40.0},
                         module.sample(0).__dict__)

    def test_deterministic_sequence(self):
        self.assertEqual([0, 1, 2], [s['sequence'] for s in module.simulate()])
        self.assertEqual(20.5, module.simulate()[2]['temperature_c'])

    def test_invalid_sequence(self):
        for value in (-1, 1001, True, '1'):
            with self.assertRaises(ValueError): module.sample(value)

    def test_invalid_count(self):
        for value in (0, 33, False, '3'):
            with self.assertRaises(ValueError): module.simulate(value)

    def test_humidity_bound(self):
        samples = module.simulate(32)
        self.assertTrue(all(40 <= s['humidity_pct'] <= 43 for s in samples))


if __name__ == '__main__':
    result = unittest.TextTestRunner(stream=io.StringIO()).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(SensorTests))
    if not result.wasSuccessful() or result.testsRun != 5:
        raise SystemExit('SENSORBRIDGE_CHECKS_FAILED')
    print('SENSORBRIDGE_CHECKS_V1 PASS '+str(result.testsRun))
