#!/usr/bin/env python
r"""
Create a Kodi add-on repository from GitHub sources

This tool extracts Kodi add-ons from their respective Git repositories and
copies the appropriate files into a Kodi add-on repository. Each add-on is
in its own directory. Each contains the add-on metadata files and a zip
archive. In addition, the repository catalog "addons.xml" is placed in the
repository folder.

Each add-on location is specified with a URL using the format:
  REPOSITORY_URL#BRANCH:PATH
The first segment is the Git URL that would be used to clone the repository,
(e.g., "https://github.com/chadparry/kodi-repository.chad.parry.org.git"). That
is followed by an optional "#" sign and a branch or tag name, (e.g.
"release-1.0"). If no branch name is specified, then the default is the cloned
repository's currently active branch, which is the same behavior as git-clone.
Next comes an optional ":" sign and path. The path denotes the location of the
add-on within the repository. If no path is specified, then the default is ".".
If the Git URL contains a colon, (which is likely), then a path must be
specified, (even if it is only "."), or else the URL's colon will be
interpreted as the delimiter.

As an example, here is the command that generates Chad Parry's Repository:
    ./create_repository.py \
        --target=html/software/kodi/ \
        --addon=https://github.com/chadparry/\
kodi-repository.chad.parry.org.git#release-latest:repository.chad.parry.org \
        --addon=https://github.com/chadparry/\
kodi-plugin.program.remote.control.browser.git#release-latest\
:plugin.program.remote.control.browser
"""
 
import addons_xml_generator
import argparse
import collections
import git
import os
import re
import shutil
import sys
import tempfile
import threading
import xml.etree.ElementTree
import zipfile
 

AddonMetadata = collections.namedtuple('AddonMetadata', ('id', 'version'))
WorkerResult = collections.namedtuple(
        'WorkerResult', ('addon_metadata', 'exc_info'))
AddonWorker = collections.namedtuple('AddonWorker', ('thread', 'result_slot'))


def fetch_addon(addon, working_folder):
    match = re.match('(.*?)(?:#([^#]*?))?(?::([^:]*))?$', addon)
    (clone_repo, clone_branch, clone_path) = match.group(1, 2, 3)
    clone_folder = tempfile.mkdtemp('repo-')
    try:
        cloned = git.Repo.clone_from(clone_repo, clone_folder)
        if clone_branch is not None:
            cloned.git.checkout(clone_branch)
        clone_source = os.path.join(clone_folder, clone_path or '.')

        metadata_path = os.path.join(clone_source, 'addon.xml')
        tree = xml.etree.ElementTree.parse(metadata_path)
        root = tree.getroot()
        addon_metadata = AddonMetadata(root.get('id'), root.get('version'))
        if (addon_metadata.id is None or
                re.search('[^a-z0-9._-]', addon_metadata.id)):
            raise RuntimeError('Invalid addon ID: ' + str(addon_metadata.id))
        if (addon_metadata.version is None or
                not re.match(r'\d+\.\d+\.\d+', addon_metadata.version)):
            raise RuntimeError('Invalid addon verson: ' +
                    str(addon_metadata.version))

        clone_target = os.path.join(working_folder, addon_metadata.id)
        shutil.copytree(clone_source, clone_target)

        return addon_metadata
    finally:
        shutil.rmtree(clone_folder, ignore_errors=False)


def fetch_addon_worker(addon, working_folder, result_slot):
    try:
        addon_metadata = fetch_addon(addon, working_folder)
        result_slot.append(WorkerResult(addon_metadata, None))
    except:
        result_slot.append(WorkerResult(None, sys.exc_info()))


def copy_addon(addon_metadata, source_folder, target_folder):
    source_addon_folder = os.path.join(source_folder, addon_metadata.id)
    target_addon_folder = os.path.join(target_folder, addon_metadata.id)
    if not os.path.isdir(target_addon_folder):
        os.mkdir(target_addon_folder)
    for basename in (
            'addon.xml',
            'changelog.txt',
            'icon.png',
            'fanart.jpg',
            'LICENSE.txt'):
        source_path = os.path.join(source_addon_folder, basename)
        if os.path.isfile(source_path):
            shutil.copyfile(
                    source_path,
                    os.path.join(target_addon_folder, basename))

    with zipfile.ZipFile(
            os.path.join(
                    target_addon_folder,
                    '{}-{}.zip'.format(
                            addon_metadata.id,
                            addon_metadata.version)),
            'w',
            zipfile.ZIP_DEFLATED) as archive:
        for (root, dirs, files) in os.walk(source_addon_folder):
            relative_root = os.path.join(
                    addon_metadata.id,
                    os.path.relpath(root, source_addon_folder))
            for relative_path in files:
                archive.write(
                        os.path.join(root, relative_path),
                        os.path.join(relative_root, relative_path))


def get_addon_worker(addon, working_folder):
    result_slot = []
    thread = threading.Thread(target=lambda: fetch_addon_worker(
            addon, working_folder, result_slot))
    return AddonWorker(thread, result_slot)


def create_repository(addons, target_folder):
    working_folder = tempfile.mkdtemp(prefix='repo-')
    try:
        workers = [get_addon_worker(addon, working_folder) for addon in addons]
        for worker in workers:
            worker.thread.start()
        for worker in workers:
            worker.thread.join()

        metadata = []
        for worker in workers:
            try:
                result = next(iter(worker.result_slot))
            except StopIteration:
                raise RuntimeError('Addon worker did not report result')
            if result.exc_info is not None:
                raise result.exc_info[1]
            metadata.append(result.addon_metadata)

        cwd = os.getcwd()
        os.chdir(working_folder)
        try:
            addons_xml_generator.Generator()
        finally:
            os.chdir(cwd)

        if not os.path.isdir(target_folder):
            os.makedirs(target_folder)
        for basename in ('addons.xml', 'addons.xml.md5'):
            shutil.copyfile(
                    os.path.join(working_folder, basename),
                    os.path.join(target_folder, basename))
        for addon_metadata in metadata:
            copy_addon(addon_metadata, working_folder, target_folder)
    finally:
        shutil.rmtree(working_folder, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser(
            description='Create a Kodi add-on repository from GitHub sources')
    parser.add_argument(
            '--target', required=True, help='Path to create the repository')
    parser.add_argument(
            '--addon', action='append', help='REPOSITORY_URL#BRANCH:PATH')
    args = parser.parse_args()

    create_repository(args.addon, args.target)


if __name__ == "__main__":
    main()
