"""Bounded PNG oracle inputs; generated codec fixtures are not browser evidence."""
import binascii
import hashlib
import importlib
import importlib.util
import struct
import unittest
import zlib

SIGNATURE = b'\x89PNG\r\n\x1a\n'


def chunk(name, raw):
    return struct.pack('>I', len(raw)) + name + raw + struct.pack('>I', binascii.crc32(name + raw) & 0xFFFFFFFF)


def png(*, width=2, height=2, color=6, rows=None, compression=0, interlace=0):
    header = struct.pack('>IIBBBBB', width, height, 8, color, compression, 0, interlace)
    scanlines = (b'\0' + b'\xff\xff\xff\xff' + b'\0\0\0\xff') * 2 if rows is None else rows
    return SIGNATURE + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(scanlines)) + chunk(b'IEND', b'')


class RenderObservationTests(unittest.TestCase):
    def decoder(self):
        name = 'runtime.mission.render_observation'
        self.assertIsNotNone(importlib.util.find_spec(name), 'Host-side bounded screenshot oracle is missing')
        module = importlib.import_module(name)
        self.assertTrue(callable(getattr(module, 'decode_png_summary', None)))
        return module.decode_png_summary

    def test_verified_pixels_and_digest_come_from_the_exact_png_bytes(self):
        raw = png()
        value = self.decoder()(raw, viewport=(2, 2))
        self.assertEqual({'width': 2, 'height': 2, 'visible_ink_pixels': 2, 'non_uniform': True,
                          'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}, value)

    def test_white_and_fully_transparent_pixels_do_not_prove_visible_content(self):
        for pixel in (b'\xff\xff\xff\xff', b'\0\0\0\0'):
            with self.subTest(pixel=pixel):
                raw = png(rows=(b'\0' + pixel * 2) * 2)
                value = self.decoder()(raw, viewport=(2, 2))
                self.assertEqual(0, value['visible_ink_pixels'])
                self.assertFalse(value['non_uniform'])

    def test_png_crc_corruption_is_refused(self):
        raw = bytearray(png());raw[-1] ^= 1
        with self.assertRaises(ValueError):
            self.decoder()(bytes(raw), viewport=(2, 2))

    def test_truncated_signatures_lengths_and_missing_end_are_refused(self):
        for raw in (b'', b'not png', png()[:20], png()[:-12], SIGNATURE + struct.pack('>I', 2**31) + b'IDAT'):
            with self.subTest(bytes=len(raw)), self.assertRaises(ValueError):
                self.decoder()(raw, viewport=(2, 2))

    def test_viewport_dimensions_and_pixel_budget_are_checked_before_inflate(self):
        for width, height, viewport in ((0, 2, (2, 2)), (3, 2, (2, 2)),
                                        (2**31, 2, (2**31, 2)), (1024, 1024, (1024, 1024))):
            with self.subTest(width=width, height=height), self.assertRaises(ValueError):
                self.decoder()(png(width=width, height=height), viewport=viewport)

    def test_inflated_row_overrun_and_concatenated_streams_are_refused(self):
        raw = png(rows=b'X' * 1048576)
        with self.assertRaises(ValueError):
            self.decoder()(raw, viewport=(2, 2))
        header = png()[8:33]
        raw = SIGNATURE + header + chunk(b'IDAT', zlib.compress(b'\0' * 18) + zlib.compress(b'extra')) + chunk(b'IEND', b'')
        with self.assertRaises(ValueError):
            self.decoder()(raw, viewport=(2, 2))

    def test_unsupported_color_interlace_and_compression_fail_closed(self):
        for updates in ({'color': 3}, {'interlace': 1}, {'compression': 1}):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                self.decoder()(png(**updates), viewport=(2, 2))

    def test_unknown_critical_chunk_duplicate_header_and_trailing_bytes_are_refused(self):
        raw = png();header = raw[8:33]
        for changed in (raw[:33] + chunk(b'ABCD', b'x') + raw[33:],
                        raw[:33] + header + raw[33:], raw + b'trailing'):
            with self.subTest(bytes=len(changed)), self.assertRaises(ValueError):
                self.decoder()(changed, viewport=(2, 2))

    def test_invalid_scanline_filter_and_short_pixel_data_are_refused(self):
        for rows in ((b'\5' + b'\xff' * 8) * 2, b'\0' + b'\xff' * 7):
            with self.subTest(bytes=len(rows)), self.assertRaises(ValueError):
                self.decoder()(png(rows=rows), viewport=(2, 2))

    def test_rgb_without_alpha_is_supported_without_inventing_transparency(self):
        rows = (b'\0' + b'\xff\xff\xff' + b'\0\0\0') * 2
        value = self.decoder()(png(color=2, rows=rows), viewport=(2, 2))
        self.assertEqual(2, value['visible_ink_pixels'])
        self.assertTrue(value['non_uniform'])

    def test_each_standard_png_filter_reconstructs_the_same_pixels(self):
        row = b'\xff\xff\xff\xff\0\0\0\xff'
        for kind in range(5):
            prior = bytes(8);filtered = bytearray()
            for _ in range(2):
                filtered.append(kind)
                for x, value in enumerate(row):
                    left, up, diagonal = (row[x-4] if x >= 4 else 0), prior[x], (prior[x-4] if x >= 4 else 0)
                    if kind == 4:
                        p = left + up - diagonal
                        distances = (abs(p-left), abs(p-up), abs(p-diagonal))
                        predictor = (left, up, diagonal)[distances.index(min(distances))]
                    else:
                        predictor = (0, left, up, (left+up)//2)[kind]
                    filtered.append((value-predictor) & 255)
                prior = row
            with self.subTest(filter=kind):
                value = self.decoder()(png(rows=bytes(filtered)), viewport=(2, 2))
                self.assertEqual(2, value['visible_ink_pixels'])
                self.assertTrue(value['non_uniform'])

    def test_zero_length_and_split_consecutive_idat_chunks_are_valid(self):
        raw = png()
        length = struct.unpack('>I', raw[33:37])[0]
        content = raw[41:41+length]
        changed = (raw[:33] + chunk(b'IDAT', b'') + chunk(b'IDAT', content[:3])
                   + chunk(b'IDAT', content[3:]) + chunk(b'IEND', b''))
        self.assertEqual(2, self.decoder()(changed, viewport=(2, 2))['visible_ink_pixels'])

    def test_unsupported_transparency_animation_and_unknown_ancillary_cannot_fake_ink(self):
        raw = png(color=2, rows=(b'\0' + b'\0\0\0' * 2) * 2)
        for name, value in ((b'tRNS', b'\0' * 6), (b'acTL', struct.pack('>II', 1, 0)), (b'abCd', b'x')):
            changed = raw[:33] + chunk(name, value) + raw[33:]
            with self.subTest(chunk=name), self.assertRaises(ValueError):
                self.decoder()(changed, viewport=(2, 2))

    def test_known_ancillary_metadata_has_closed_size_values_and_order(self):
        raw = png()
        for name, value in ((b'sRGB', b''), (b'sRGB', b'\4'),
                            (b'gAMA', b'\0' * 4), (b'gAMA', b'\1'),
                            (b'pHYs', struct.pack('>IIB', 1, 1, 2))):
            with self.subTest(chunk=name, length=len(value)), self.assertRaises(ValueError):
                self.decoder()(raw[:33] + chunk(name, value) + raw[33:], viewport=(2, 2))
