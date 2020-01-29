#!/usr/bin/env python3

import sys
import argparse
import logging
import logging.handlers
import struct
import os.path
import datetime
import glob

# TODO  - there is localtime but we need UTC, what to do???
#       - save to the same dir as mp4
#       - support dir only
# srt, log, mux srt, concat video, trip detection (provide max segment length - 3 min)
# compile to exe


# filename is like NO20200127-170409-000017_s.MP4 - required to get absolute time start!!
def parse_70mai_mp4(in_file, force=False):
    logging.debug('About to parse "{}"'.format(in_file))

    fpath = os.path.dirname(in_file)
    # or os.path.dirname(os.path.realpath(__file__)) ???

    fname, fext = os.path.splitext(os.path.basename(in_file))
    if fext.lower() != '.mp4':
        logging.error('Expected mp4 file, not \"{}\"'.format(in_file))
        return

    if fname[:2] != "NO" or len(fname)<24:
        logging.error('Expected 70mai file, not \"{}\"'.format(in_file))
        return

    timestamp = fname[2:17]
    try:
        ftime = datetime.datetime.strptime(timestamp + " CET", "%Y%m%d-%H%M%S %Z")
    except ValueError:
        logging.error("Cannot parse timestamp from \"{}\"".format(timestamp))
        return
    # print(ftime.tzinfo)
    logging.debug("Parsed time from \"{}\" as {}".format(fname, ftime))

    gps_data = []

    # go over top level atoms
    out_filename = os.path.join(fpath, fname+".log")
    logging.info("Will create {} for {}".format(out_filename, in_file))
    
    if os.path.isfile(out_filename):
        if force:
            logging.info("File {} already exists, will overwrite it because of force flag".format(out_filename))
        else:
            logging.info("File {} already exists, will skip it as there is no force flag".format(out_filename))
            return

    try:
        outfile = open(out_filename, "wt")
    except FileNotFoundError:
        logging.error("Cannot open {} for writing".format(out_filename))
        return

    with open(in_file, "rb") as f:
        offset = 0

        while True:
            atom_pos = f.tell()

            atom_header = f.read(8)
            if len(atom_header) < 8:
                logging.debug("End od file reached at {} while reading atom header".format(offset))
                break
            try:
                atom_size, atom_type = struct.unpack('>I4s', atom_header)
            except struct.error:
                logging.error("Cannot parse atom header in \"{}\" at offset {}".format(in_file, offset))
                return

            atom_type = atom_type.decode('ascii')
            logging.debug("Found atom \"{}\" size {}".format(atom_type, atom_size))

            if atom_size == 0:
                logging.debug("This was the last top level atom - data till the end of the file")
                break

            # big atom >2^32 B
            if atom_size == 1:
                offset += 8
                size64b = f.read(8)
                if len(size64b) < 8:
                    logging.error("Unexpected enf of file at {} while reading big atom size".format(offset))
                    break

                atom_size, = struct.unpack('>Q', size64b)
                logging.debug("Atom \"{}\" is big, its real size is {}".format(atom_type, atom_size))

            if atom_type == 'GPS ':
                logging.debug("Found GPS atom...")

                gps_size = 8
                while gps_size+36 <= atom_size:
                    record = f.read(36)
                    if len(record) < 36:
                        logging.error("Unexpected enf of file at {} while reading GPS record".format(offset))
                        break
                    try:
                        f1, f2, time_diff, speed, clat, lat, clon, lon, rest = struct.unpack('<IIIIcici10s', record)
                    except struct.error:
                        logging.error("Cannot parse GPS data in \"{}\" at offset {}".format(in_file, offset))
                        break

                    clat = clat.decode('ascii')
                    clon = clon.decode('ascii')
                    logging.debug("f1={}, f2={}, time={}, speed={}, clat {}, lat {}, clon {}, lon {}".format(f1, f2, time_diff, speed, clat, lat, clon, lon))

                    real_speed = float(speed) / 1000.0

                    timestamp = ftime + datetime.timedelta(seconds=time_diff)
                    text = ""
                    if f2==1:
                        # valid GPS data
                        text = "A,{:02d}{:02d}{:02d},{:02d}{:02d}{:02d}.000,{:8.4f},{},{:8.4f},{},{:.2f},,,,;".format(timestamp.day,
                                                                                                                  timestamp.month,
                                                                                                                  timestamp.year % 100,
                                                                                                                  timestamp.hour,
                                                                                                                  timestamp.minute,
                                                                                                                  timestamp.second,
                                                                                                                  float(lat)/1000.0,
                                                                                                                  clat,
                                                                                                                  float(lon)/1000.0,
                                                                                                                  clon,
                                                                                                                  float(speed)/1000.0/1.852)
                    else:
                        # no GPS data...
                        text = "V,{:02d}{:02d}{:02d},{:02d}{:02d}{:02d}.000,,,,,,M,,,;".format(timestamp.day,
                                                                                               timestamp.month,
                                                                                               timestamp.year % 100,
                                                                                               timestamp.hour,
                                                                                               timestamp.minute,
                                                                                               timestamp.second)

                    logging.debug(text)
                    outfile.write(text + "\n")

                    gps_size += 36

                if gps_size != atom_size:
                    logging.warning("Some data left, %d != %d", gps_size, atom_size)

            offset += atom_size
            f.seek(offset, 0)

    outfile.close()


def list_files(directory, pattern='*.MP4'):
    file_list = glob.glob(os.path.join(directory, pattern))
    logging.debug("Found in \"{}\" files: {}".format(directory, file_list))
    return file_list


def main():
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s'
                        )
    
    rootLogger = logging.getLogger()

    logging.addLevelName( logging.INFO, "\033[93m%s\033[1;0m" % logging.getLevelName(logging.INFO))
    logging.addLevelName( logging.WARNING, "\033[1;31m%s\033[1;0m" % logging.getLevelName(logging.WARNING))
    logging.addLevelName( logging.ERROR, "\033[1;41m%s\033[1;0m" % logging.getLevelName(logging.ERROR))


    parser = argparse.ArgumentParser()
    parser.add_argument('-i', '--input-file',
                        dest    = 'inFile',
                        metavar = 'INFILE',
                        action  = 'append',
                        help    = 'Process single MP4 file (can be repeated)'
                       )

    parser.add_argument('-v', '--verbose',
                        dest    = 'debugOn',
                        action  = 'store_true',
                        default = False,
                        help    = 'Verbose / debug info.'
                       )

    parser.add_argument('-f', '--force',
                        dest    = 'force',
                        action  = 'store_true',
                        default = False,
                        help    = 'Force generation / overwrite previous logs/srt. Skip otherwise (default).'
                       )

    parser.add_argument('-d', '--dir',
                        dest    = 'directory',
                        metavar = 'DIRECTORY',
                        help    = 'Process all files in the given directory'
                       )

    options = parser.parse_args()
    
    if(options.debugOn):
        rootLogger.setLevel(logging.DEBUG)        
        logging.info("Verbose ON")


    #-----------
    in_files = []
    if options.inFile:
        in_files.extend(options.inFile)

    if options.directory:
        in_files.extend(list_files(options.directory))

    logging.debug("Will process {}, force {}".format(in_files, options.force))

    # sys.exit(1)

    if len(in_files) > 0:
        for f in in_files:
            parse_70mai_mp4(f, options.force)


    
if __name__ == "__main__":
    main()
