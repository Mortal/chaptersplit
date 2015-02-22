import os
import re
import shutil
import argparse
import tempfile
import subprocess
import collections
import unicodedata


REQUIRED_PROGRAMS = {
    'ffprobe': 'ffmpeg',
    'ffmpeg': 'ffmpeg',
    'lame': 'lame',
    'mp3splt': 'mp3splt',
    'id3tag': 'id3lib',
}


def check_required_programs():
    missing = collections.defaultdict(list)
    for program, package in REQUIRED_PROGRAMS.items():
        path = shutil.which(program)
        if path is None:
            missing[package].append(program)

    for package, programs in missing.items():
        print(("Required program%s %s not found. " +
               "Consider installing the %s package.") %
              ('' if len(programs) == 1 else 's',
               ', '.join(programs), package))

    if missing:
        raise SystemExit(1)


def normalize(title):
    unicode_normalized = unicodedata.normalize('NFKC', title)
    return unicode_normalized.translate({
        8217: '\'',
    })


def get_chapters(filename):
    data = subprocess.check_output(
        ('ffprobe', filename),
        stdin=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        universal_newlines=True)
    lines = data.splitlines()
    titles = {
        i-2: normalize(o.group(1))
        for i, o in enumerate(
            re.match(r'      title           : (.*)', line)
            for line in lines)
        if o is not None
    }
    markers = {
        i: (o.group(1), o.group(2))
        for i, o in enumerate(
            re.match(
                r'    Chapter #\d+[.:]\d+: start ([\d.]+), end ([\d.]+)', line)
            for line in lines)
        if o is not None
    }
    indices = sorted(set(titles.keys()) & set(markers.keys()))
    if not indices:
        print("No indices")
        print(repr(titles))
        print(repr(markers))
    chapters = [
        (titles[i], markers[i][0], markers[i][1])
        for i in indices
    ]
    # print("Chapters:")
    # print('\n'.join(
    #     "%s. %s (from %s to %s)" % (i, d[0], d[1], d[2])
    #     for i, d in enumerate(chapters)))
    for ch_i, ch_j in zip(chapters[:-1], chapters[1:]):
        if ch_i[2] != ch_j[1]:
            raise Exception(
                "Chapters are not contiguous: %s != %s" % (ch_i[2], ch_j[1]))

    return chapters


def get_output_name(i, title):
    title_escaped = title.replace('/', '_')
    return '%02d. %s' % (i+1, title_escaped)


def write_chapters(fp, chapters):
    for i, data in enumerate(chapters):
        title, start, end = data
        filename = get_output_name(i, title)
        fp.write('%s\t%s\t%s\n' % (start, end, filename))
    fp.flush()


def basename(filename):
    base, ext = os.path.splitext(os.path.basename(filename))
    return base


def get_mp3(input_file, output_dir):
    mp3_name = os.path.join(output_dir, '%s.mp3' % basename(input_file))
    if not os.path.exists(mp3_name):
        try:
            ffmpeg = subprocess.Popen(
                ('ffmpeg', '-i', input_file, '-f', 'wav', '-'),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE)
            ffmpeg.stdin.close()
            subprocess.check_call(
                ('lame', '-V', '4', '-', mp3_name),
                stdin=ffmpeg.stdout)
        except:
            if os.path.exists(mp3_name):
                os.path.remove(mp3_name)
            raise
    return mp3_name


def main():
    parser = argparse.ArgumentParser(description="""
        Split an MP4 file into MP3 files based on the embedded chapters.
        Uses shellouts to ffmpeg, lame, mp3splt and id3tag to do the
        processing.
        """)
    parser.add_argument('-i', '--input-file', required=True)
    parser.add_argument('-o', '--output-dir', required=True)
    parser.add_argument('-a', '--artist', required=True)
    parser.add_argument('-A', '--album', required=True)
    parser.add_argument('-y', '--year', required=True)
    try:
        args = parser.parse_args()
    finally:
        # If parse_args registers bad arguments,
        # we still want to give an error about missing programs.
        check_required_programs()

    if not os.path.exists(args.output_dir):
        os.mkdir(args.output_dir)

    chapters = get_chapters(args.input_file)
    if not chapters:
        raise Exception("get_chapters returned nothing")
    full_mp3 = get_mp3(args.input_file, args.output_dir)
    delete = True
    fp = tempfile.NamedTemporaryFile('w+', delete=False)
    try:
        write_chapters(fp, chapters)
        subprocess.check_call(
            ('mp3splt', '-A', fp.name, '-d', args.output_dir, full_mp3))
    except:
        delete = False
        print("mp3splt failed with labels in %r" % (fp.name,))
        raise
    finally:
        if delete:
            os.remove(fp.name)
    for i, data in enumerate(chapters):
        title, start, end = data
        filename = os.path.join(
            args.output_dir, '%s.mp3' % get_output_name(i, title))
        subprocess.check_call(
            ('id3tag',
             b'--artist=' + args.artist.encode('latin1'),
             b'--album=' + args.album.encode('latin1'),
             b'--song=' + title.encode('latin1'),
             b'--track=' + str(i+1).encode('latin1'),
             b'--total=' + str(len(chapters)).encode('latin1'),
             filename))


if __name__ == "__main__":
    main()
