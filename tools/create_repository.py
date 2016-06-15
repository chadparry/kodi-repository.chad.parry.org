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

As an example, here is the command that generates Chad Parry's Repository:
    ./create_repository.py \
        --target=html/software/kodi/ \
        --addon=https://github.com/chadparry/\
kodi-repository.chad.parry.org.git#release-latest:repository.chad.parry.org \
        --addon=https://github.com/chadparry/\
kodi-plugin.program.remote.control.browser.git#release-latest\
:plugin.program.remote.control.browser
"""
 
import argparse
import collections
import git
import hashlib
import os
import re
import shutil
import sys
import tempfile
import threading
import xml.etree.ElementTree
 

AddonMetadata = collections.namedtuple(
        'AddonMetadata', ('id', 'version', 'root'))
WorkerResult = collections.namedtuple(
        'WorkerResult', ('addon_metadata', 'exc_info'))
AddonWorker = collections.namedtuple('AddonWorker', ('thread', 'result_slot'))


def fetch_addon(addon, target_folder):
    # Parse the format "REPOSITORY_URL#BRANCH:PATH". The colon is a delimiter
    # unless it looks more like a scheme, (e.g., "http://").
    match = re.match(
            '((?:[A-Za-z0-9+.-]+://)?.*?)(?:#([^#]*?))?(?::([^:]*))?$',
            addon)
    (clone_repo, clone_branch, clone_path) = match.group(1, 2, 3)

    # Create a temporary folder for the git clone.
    clone_folder = tempfile.mkdtemp('repo-')
    try:
        # Check out the sources.
        cloned = git.Repo.clone_from(clone_repo, clone_folder)
        if clone_branch is not None:
            cloned.git.checkout(clone_branch)
        clone_source_folder = os.path.join(clone_folder, clone_path or '.')

        # Parse the addon.xml metadata.
        metadata_path = os.path.join(clone_source_folder, 'addon.xml')
        tree = xml.etree.ElementTree.parse(metadata_path)
        root = tree.getroot()
        addon_metadata = AddonMetadata(
                root.get('id'),
                root.get('version'),
                root)
        # Validate the add-on ID.
        if (addon_metadata.id is None or
                re.search('[^a-z0-9._-]', addon_metadata.id)):
            raise RuntimeError('Invalid addon ID: ' + str(addon_metadata.id))
        if (addon_metadata.version is None or
                not re.match(r'\d+\.\d+\.\d+', addon_metadata.version)):
            raise RuntimeError('Invalid addon verson: ' +
                    str(addon_metadata.version))

        # Create the compressed add-on archive.
        addon_target_folder = os.path.join(target_folder, addon_metadata.id)
        if not os.path.isdir(addon_target_folder):
            os.mkdir(addon_target_folder)
        archive_path = os.path.join(
                addon_target_folder,
                '{}-{}.zip'.format(
                        addon_metadata.id,
                        addon_metadata.version))
        with open(archive_path, 'wb') as archive:
            cloned.archive(
                    archive,
                    treeish='HEAD:{}'.format(clone_path),
                    prefix='{}/'.format(addon_metadata.id),
                    format='zip')

        # Copy all the add-on metadata files.
        for basename in (
                'addon.xml',
                'changelog.txt',
                'icon.png',
                'fanart.jpg',
                'LICENSE.txt'):
            source_path = os.path.join(clone_source_folder, basename)
            if os.path.isfile(source_path):
                shutil.copyfile(
                        source_path,
                        os.path.join(addon_target_folder, basename))

        return addon_metadata
    finally:
        shutil.rmtree(clone_folder, ignore_errors=False)


def fetch_addon_worker(addon, target_folder, result_slot):
    try:
        addon_metadata = fetch_addon(addon, target_folder)
        result_slot.append(WorkerResult(addon_metadata, None))
    except:
        result_slot.append(WorkerResult(None, sys.exc_info()))


def get_addon_worker(addon, target_folder):
    result_slot = []
    thread = threading.Thread(target=lambda: fetch_addon_worker(
            addon, target_folder, result_slot))
    return AddonWorker(thread, result_slot)


def create_repository(addons, target_folder):
    # Create the target folder.
    if not os.path.isdir(target_folder):
        os.makedirs(target_folder)

    # Fetch all the add-on sources in parallel.
    workers = [get_addon_worker(addon, target_folder) for addon in addons]
    for worker in workers:
        worker.thread.start()
    for worker in workers:
        worker.thread.join()

    # Collect the results from all the threads.
    metadata = []
    for worker in workers:
        try:
            result = next(iter(worker.result_slot))
        except StopIteration:
            raise RuntimeError('Addon worker did not report result')
        if result.exc_info is not None:
            raise result.exc_info[1]
        metadata.append(result.addon_metadata)

    # Generate the addons.xml file.
    root = xml.etree.ElementTree.Element('addons')
    for addon_metadata in metadata:
        root.append(addon_metadata.root)
    tree = xml.etree.ElementTree.ElementTree(root)
    addons_path = os.path.join(target_folder, 'addons.xml')
    tree.write(addons_path, encoding='utf-8', xml_declaration=True)

    # Calculate the signature.
    with open(addons_path, 'rb') as addons:
        digest = hashlib.md5(addons.read()).hexdigest()
    with open(os.path.join(target_folder, 'addons.xml.md5'), 'w') as sig:
        sig.write(digest)


def main():
    parser = argparse.ArgumentParser(
            description='Create a Kodi add-on repository from GitHub sources')
    parser.add_argument(
            '--target', required=True, help='Path to create the repository')
    parser.add_argument(
            '--addon',
            action='append',
            default=[],
            help='REPOSITORY_URL#BRANCH:PATH')
    args = parser.parse_args()

    create_repository(args.addon, args.target)


if __name__ == "__main__":
    main()
