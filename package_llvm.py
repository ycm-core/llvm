#!/usr/bin/env python3

import argparse
import collections
import functools
import os
import platform
import re
import requests
import stat
import shutil
import subprocess
import sys
import tarfile
import time

DIR_OF_THIS_SCRIPT = os.path.dirname( os.path.abspath( __file__ ) )

CHUNK_SIZE = 1024 * 1024 # 1MB

LLVM_RELEASE_URL = (
  'https://github.com/llvm/llvm-project/releases/'
  'download/llvmorg-{version}' )
LLVM_PRERELEASE_URL = (
  'https://github.com/llvm/llvm-project/releases/'
  'download/llvmorg-{version}-rc{release_candidate}' )
LLVM_SOURCE = 'llvm-{version}.src'
CLANG_SOURCE = 'clang-{version}.src'
CLANG_TOOLS_SOURCE = 'clang-tools-extra-{version}.src'
BUNDLE_NAME = 'clang+llvm-{version}-{target}'
TARGET_REGEX = re.compile( '^Target: (?P<target>.*)$' )
GITHUB_BASE_URL = 'https://api.github.com/'
GITHUB_RELEASES_URL = (
  GITHUB_BASE_URL + 'repos/{owner}/{repo}/releases' )
GITHUB_ASSETS_URL = (
  GITHUB_BASE_URL + 'repos/{owner}/{repo}/releases/assets/{asset_id}' )
RETRY_INTERVAL = 10
SHARED_LIBRARY_REGEX = re.compile( '.*\.so(.\d+)*$' )

OBJDUMP_NEEDED_REGEX = re.compile(
  '^  NEEDED               (?P<dependency>.*)$' )
OBJDUMP_VERSION_REGEX = re.compile(
  '^    0x[0-9a-f]+ 0x00 \d+ (?P<library>.*)_(?P<version>.*)$' )


@functools.total_ordering
class Version( object ):

  def __init__( self, version ):
    split_version = version.split( '.' )
    self.major = int( split_version[ 0 ] )
    self.minor = int( split_version[ 1 ] ) if len( split_version ) > 1 else 0
    self.patch = int( split_version[ 2 ] ) if len( split_version ) > 2 else 0


  def __eq__( self, other ):
    if not isinstance( other, Version ):
      raise ValueError( 'Must be compared with a Version object.' )
    return ( ( self.major, self.minor, self.patch ) == 
             ( other.major, other.minor, other.patch ) )


  def __lt__( self, other ):
    if not isinstance( other, Version ):
      raise ValueError( 'Must be compared with a Version object.' )
    return ( ( self.major, self.minor, self.patch ) <
             ( other.major, other.minor, other.patch ) )


  def __repr__( self ):
    return '.'.join( ( str( self.major ),
                       str( self.minor ),
                       str( self.patch ) ) )



def Retries( function, *args ):
  max_retries = 3
  nb_retries = 0
  while True:
    try:
      function( *args )
    except SystemExit as error:
      nb_retries = nb_retries + 1
      print( 'ERROR: {0} Retry {1}. '.format( error, nb_retries ) )
      if nb_retries > max_retries:
        sys.exit( 'Number of retries exceeded ({0}). '
                  'Aborting.'.format( max_retries ) )
      time.sleep( RETRY_INTERVAL )
    else:
      return True


def Download( url ):
  dest = url.rsplit( '/', 1 )[ -1 ]
  print( 'Downloading {}.'.format( os.path.basename( dest ) ) )
  r = requests.get( url, stream = True )
  r.raise_for_status()
  with open( dest, 'wb') as f:
    for chunk in r.iter_content( chunk_size = CHUNK_SIZE ):
      if chunk:
        f.write( chunk )
  r.close()


def Extract( archive ):
  print( 'Extract archive {0}.'.format( archive ) )
  with tarfile.open( archive ) as f:
    f.extractall( '.' )


def GetLlvmBaseUrl( args ):
  if args.release_candidate:
    return LLVM_PRERELEASE_URL.format(
      version = args.version,
      release_candidate = args.release_candidate )

  return LLVM_RELEASE_URL.format( version = args.version )


def GetLlvmVersion( args ):
  if args.release_candidate:
    return args.version + 'rc' + str( args.release_candidate )
  return args.version


def GetBundleVersion( args ):
  if args.release_candidate:
    return args.version + '-rc' + str( args.release_candidate )
  return args.version


def DownloadSource( url, source ):
  archive = source + '.tar.xz'

  if not os.path.exists( archive ):
    Download( url + '/' + archive )

  if not os.path.exists( source ):
    Extract( archive )


def MoveClangSourceToLlvm( clang_source, llvm_source ):
  os.rename( clang_source, 'clang' )
  shutil.move(
    os.path.join( DIR_OF_THIS_SCRIPT, 'clang' ),
    os.path.join( DIR_OF_THIS_SCRIPT, llvm_source, 'tools' )
  )


def MoveClangToolsSourceToLlvm( clang_tools_source, llvm_source ):
  os.rename( clang_tools_source, 'extra' )
  shutil.move(
    os.path.join( DIR_OF_THIS_SCRIPT, 'extra' ),
    os.path.join( DIR_OF_THIS_SCRIPT, llvm_source, 'tools', 'clang', 'tools' )
  )


def BuildLlvm( build_dir, install_dir, llvm_source ):
  try:
    os.chdir( build_dir )
    cmake = shutil.which( 'cmake' )
    # See https://llvm.org/docs/CMake.html#llvm-specific-variables for the CMake
    # variables defined by LLVM.
    subprocess.check_call( [
      cmake,
      '-G', 'Unix Makefiles',
      # A release build implies LLVM_ENABLE_ASSERTIONS=OFF.
      '-DCMAKE_BUILD_TYPE=Release',
      '-DCMAKE_INSTALL_PREFIX={}'.format( install_dir ),
      '-DLLVM_TARGETS_TO_BUILD=all',
      '-DLLVM_INCLUDE_EXAMPLES=OFF',
      '-DLLVM_INCLUDE_TESTS=OFF',
      '-DLLVM_INCLUDE_GO_TESTS=OFF',
      '-DLLVM_INCLUDE_DOCS=OFF',
      '-DLLVM_ENABLE_TERMINFO=OFF',
      '-DLLVM_ENABLE_ZLIB=OFF',
      '-DLLVM_ENABLE_LIBEDIT=OFF',
      '-DLLVM_ENABLE_LIBXML2=OFF',
      os.path.join( DIR_OF_THIS_SCRIPT, llvm_source )
    ] )

    subprocess.check_call( [ cmake, '--build', '.', '--target', 'install' ] )
  finally:
    os.chdir( DIR_OF_THIS_SCRIPT )


def CheckDependencies( name, path, versions ):
  dependencies = []
  objdump = shutil.which( 'objdump' )
  output = subprocess.check_output( [ objdump, '-p', path ],
    stderr = subprocess.STDOUT ).decode( 'utf8' )
  for line in output.splitlines():
    match = OBJDUMP_NEEDED_REGEX.search( line )
    if match:
      dependencies.append( match.group( 'dependency' ) )

    match = OBJDUMP_VERSION_REGEX.search( line )
    if match:
      library = match.group( 'library' )
      version = Version( match.group( 'version' ) )
      versions[ library ].append( version )

  print( 'List of {} dependencies:'.format( name ) )
  for dependency in dependencies:
    print( dependency )


def CheckLlvm( install_dir ):
  print( 'Checking LLVM dependencies.' )
  versions = collections.defaultdict( list )
  CheckDependencies(
    'libclang', os.path.join( install_dir, 'lib', 'libclang.so' ), versions )
  CheckDependencies(
    'clangd', os.path.join( install_dir, 'bin', 'clangd' ), versions )

  print( 'Maximum versions required:' )
  for library, values in versions.items():
    print( library + ' ' + str( max( values ) ) )


def GetTarget( install_dir ):
  output = subprocess.check_output(
    [ os.path.join( install_dir, 'bin', 'clang' ), '-###' ],
    stderr = subprocess.STDOUT ).decode( 'utf8' )
  for line in output.splitlines():
    match = TARGET_REGEX.search( line )
    if match:
      return match.group( 'target' )
  sys.exit( 'Cannot deduce LLVM target.' )


def BundleLlvm( bundle_name, archive_name, install_dir, version ):
  print( 'Bundling LLVM to {}.'.format( archive_name ) )
  with tarfile.open( name = archive_name, mode = 'w:xz' ) as tar_file:
    # The .so files are not set as executable when copied to the install
    # directory. Set them manually.
    for root, directories, files in os.walk( install_dir ):
      for filename in files:
        filepath = os.path.join( root, filename )
        if SHARED_LIBRARY_REGEX.match( filename ):
          mode = os.stat( filepath ).st_mode
          # Add the executable bit only if the file is readable for the user.
          mode |= ( mode & 0o444 ) >> 2
          os.chmod( filepath, mode )
        arcname = os.path.join( bundle_name,
                                os.path.relpath( filepath, install_dir ) )
        tar_file.add( filepath, arcname = arcname )


def UploadLlvm( args, bundle_path ):
  response = requests.get(
    GITHUB_RELEASES_URL.format( owner = args.gh_org, repo = 'llvm' ),
    auth = ( args.gh_user, args.gh_token )
  )
  if response.status_code != 200:
    message = response.json()[ 'message' ]
    sys.exit( 'Getting releases failed with message: {}'.format( message ) )

  bundle_version = GetBundleVersion( args )
  bundle_name = os.path.basename( bundle_path )

  upload_url = None
  for release in response.json():
    if release[ 'tag_name' ] != bundle_version:
      continue

    print( 'Version {} already released.'.format( bundle_version ) )
    upload_url = release[ 'upload_url' ]

    for asset in release[ 'assets' ]:
      if asset[ 'name' ] != bundle_name:
        continue

      print( 'Deleting {} on GitHub.'.format( bundle_name ) )
      response = requests.delete(
        GITHUB_ASSETS_URL.format( owner = args.gh_org,
                                  repo = 'llvm',
                                  asset_id = asset[ 'id' ] ),
        json = { 'tag_name': bundle_version },
        auth = ( args.gh_user, args.gh_token )
      )

      if response.status_code != 204:
        message = response.json()[ 'message' ]
        sys.exit( 'Creating release failed with message: {}'.format( message ) )

      break

  if not upload_url:
    print( 'Releasing {} on GitHub.'.format( bundle_version ) )
    prerelease = args.release_candidate is not None
    name = 'LLVM and Clang ' + args.version
    if args.release_candidate:
      name += ' RC' + str( args.release_candidate )
    response = requests.post(
      GITHUB_RELEASES_URL.format( owner = args.gh_org, repo = 'llvm' ),
      json = {
        'tag_name': bundle_version,
        'name': name,
        'body': name + ' without realtime, terminfo, and zlib dependencies.',
        'prerelease': prerelease
      },
      auth = ( args.gh_user, args.gh_token )
    )
    if response.status_code != 201:
      message = response.json()[ 'message' ]
      sys.exit( 'Releasing failed with message: {}'.format( message ) )

    upload_url = response.json()[ 'upload_url' ]

  upload_url = upload_url.replace( '{?name,label}', '' )

  with open( bundle_path, 'rb' ) as bundle:
    print( 'Uploading {} on GitHub.'.format( bundle_name ) )
    response = requests.post(
      upload_url,
      params = { 'name': bundle_name },
      headers = { 'Content-Type': 'application/x-xz' },
      data = bundle,
      auth = ( args.gh_user, args.gh_token )
    )

  if response.status_code != 201:
    message = response.json()[ 'message' ]
    sys.exit( 'Uploading failed with message: {}'.format( message ) )


def ParseArguments():
  parser = argparse.ArgumentParser()
  parser.add_argument( 'version', type = str, help = 'LLVM version.')
  parser.add_argument( '--release-candidate', type = int,
                       help = 'LLVM release candidate number.' )

  parser.add_argument( '--gh-user', action='store',
                       help = 'GitHub user name. Defaults to environment '
                              'variable: GITHUB_USERNAME' )
  parser.add_argument( '--gh-token', action='store',
                       help = 'GitHub api token. Defaults to environment '
                              'variable: GITHUB_TOKEN.' )
  parser.add_argument( '--gh-org', action='store',
                       default = 'ycm-core',
                       help = 'GitHub organization to which '
                              'the archive will be uploaded to. ' )

  args = parser.parse_args()

  if not args.gh_user:
    if 'GITHUB_USERNAME' not in os.environ:
      sys.exit( 'ERROR: Must specify either --gh-user or '
                'GITHUB_USERNAME in environment' )
    args.gh_user = os.environ[ 'GITHUB_USERNAME' ]

  if not args.gh_token:
    if 'GITHUB_TOKEN' not in os.environ:
      sys.exit( 'ERROR: Must specify either --gh-token or '
                'GITHUB_TOKEN in environment' )
    args.gh_token = os.environ[ 'GITHUB_TOKEN' ]

  return args


def Main():
  args = ParseArguments()
  llvm_url = GetLlvmBaseUrl( args )
  llvm_version = GetLlvmVersion( args )
  llvm_source = LLVM_SOURCE.format( version = llvm_version )
  clang_source = CLANG_SOURCE.format( version = llvm_version )
  clang_tools_source = CLANG_TOOLS_SOURCE.format( version = llvm_version )
  if not os.path.exists( os.path.join( DIR_OF_THIS_SCRIPT, llvm_source ) ):
    DownloadSource( llvm_url, llvm_source )
  if not os.path.exists( os.path.join( DIR_OF_THIS_SCRIPT, llvm_source,
                                       'tools', 'clang' ) ):
    DownloadSource( llvm_url, clang_source )
    MoveClangSourceToLlvm( clang_source, llvm_source )
  if not os.path.exists( os.path.join( DIR_OF_THIS_SCRIPT, llvm_source,
                                       'tools', 'clang', 'tools', 'extra' ) ):
    DownloadSource( llvm_url, clang_tools_source )
    MoveClangToolsSourceToLlvm( clang_tools_source, llvm_source )
  build_dir = os.path.join( DIR_OF_THIS_SCRIPT, 'build' )
  install_dir = os.path.join( DIR_OF_THIS_SCRIPT, 'install' )
  if not os.path.exists( build_dir ):
    os.mkdir( build_dir )
  if not os.path.exists( install_dir ):
    os.mkdir( install_dir )
  BuildLlvm( build_dir, install_dir, llvm_source )
  CheckLlvm( install_dir )
  target = GetTarget( install_dir )
  bundle_version = GetBundleVersion( args )
  bundle_name = BUNDLE_NAME.format( version = bundle_version, target = target )
  archive_name = bundle_name + '.tar.xz'
  bundle_path = os.path.join( DIR_OF_THIS_SCRIPT, archive_name )
  if not os.path.exists( bundle_path ):
    BundleLlvm( bundle_name, archive_name, install_dir, bundle_version )
  UploadLlvm( args, bundle_path )


if __name__ == "__main__":
  Main()
