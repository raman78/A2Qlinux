#!/usr/bin/env python3
"""Convert a recorded capture of AION 2 traffic into a Questlog replay file.

The capture must be classic pcap. A pcapng recording (dumpcap's default) is
converted first with: editcap -F pcap in.pcapng out.pcap
Play the result with QUESTLOG_REPLAY=<Windows path of the output>.
"""

import argparse
import sys

from replay_stream import ReplayWriter, read_pcap


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("capture", help="classic pcap file")
    parser.add_argument("output", help="replay file to write (.ndjson)")
    args = parser.parse_args()
    with open(args.capture, "rb") as stream, open(args.output, "w", encoding="utf-8") as out:
        writer = ReplayWriter(out)
        try:
            for segment in read_pcap(stream):
                writer.feed(segment)
        except ValueError as error:
            print(f"pcap2questlog: {error}", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
