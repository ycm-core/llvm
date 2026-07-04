#!/usr/bin/env python3

import argparse
import collections
import contextlib
import functools
import os
import platform
import re
import requests
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
LLVM_SOURCE = 'llvm-project-{version}.src'
BUNDLE_NAME = 'clang+llvm-{version}-{target}'
RETRY_INTERVAL = 10
SHARED_LIBRARY_REGEX = re.compile( r'.*\.so(.\d+)*$' )

OBJDUMP_NEEDED_REGEX = re.compile(
  '^  NEEDED               (?P<dependency>.*)$' )
OBJDUMP_VERSION_REGEX = re.compile(
  r'^    0x[0-9a-f]+ 0x00 \d+ (?P<library>.*)_(?P<version>.*)$' )

ENV_DATA = {
  'Linux': {
    'x86_64': {
      'host': 'x86_64-unknown-linux-gnu',
      'target': 'x86_64-unknown-linux-gnu',
      'archive': 'x86_64-unknown-linux-gnu'
    },
    'arm': {
      'host': 'x86_64-unknown-linux-gnu',
      'target': 'arm-linux-gnueabihf',
      'archive': 'armv7a-linux-gnueabihf'
    },
    'aarch64': {
      'host': 'x86_64-unknown-linux-gnu',
      'target': 'aarch64-linux-gnu',
      'archive': 'aarch64-linux-gnu'
    }
  },
  'Darwin': {
    'x86_64': {
      'host': 'x86_64-apple-darwin'
        if platform.processor() != 'arm' else 'arm64-apple-darwin',
      'target': 'x86_64-apple-darwin',
      'archive': 'x86_64-apple-darwin'
    },
    'arm64': {
      'host': 'x86_64-apple-darwin'
        if platform.processor() != 'arm' else 'arm64-apple-darwin',
      'target': 'arm64-apple-darwin',
      'archive': 'arm64-apple-darwin'
    }
  }
}
assert platform.system() in ENV_DATA


@contextlib.contextmanager
def WorkingDirectory( cwd ):
  old_cwd = os.getcwd()
  os.chdir( cwd )
  try:
    yield
  finally:
    os.chdir( old_cwd )


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
  with open( dest, 'wb' ) as f:
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


def GetLogicalCores():
  cmd = [ 'nproc' ]
  if platform.system() == "Darwin":
    cmd = [ 'sysctl', '-n', 'hw.logicalcpu' ]

  return subprocess.check_output( cmd ).decode( 'utf-8' ).strip()


def GetGeneratorArgs():
  return shutil.which( 'ninja' ) and [ '-G', 'Ninja' ] or []


def GetCacheArgs( build_dir ):
  return shutil.which( 'ccache' ) and [
      '-DLLVM_CCACHE_BUILD=ON',
      '-DLLVM_CCACHE_MAXSIZE=5G',
      '-DLLVM_CCACHE_DIR={}'.format(
        os.path.abspath( os.path.join( build_dir, '..', 'ccache' ) ) ),
  ] or []


def BuildLlvm( build_dir,
               install_dir,
               llvm_source_dir,
               tblgen_root,
               target_architecture ):
  host = ENV_DATA[ platform.system() ][ target_architecture ][ 'host' ]
  target = ENV_DATA[ platform.system() ][ target_architecture ][ 'target' ]
  print( 'Host triple:', host )
  print( 'Target triple:', target )
  with WorkingDirectory( build_dir ):
    cmake = shutil.which( 'cmake' )
    # See https://llvm.org/docs/CMake.html#llvm-specific-variables for the CMake
    # variables defined by LLVM.
    cmake_configure_args = [
      cmake,
      *GetGeneratorArgs(),
      # A release build implies LLVM_ENABLE_ASSERTIONS=OFF.
      '-DCMAKE_BUILD_TYPE=Release',
      '-DCMAKE_INSTALL_PREFIX={}'.format( install_dir ),
      '-DLLVM_ENABLE_PROJECTS=clang;clang-tools-extra;openmp',
      '-DLLVM_DEFAULT_TARGET_TRIPLE={}'.format( target ),
      '-DLLVM_TARGETS_TO_BUILD=all',
      '-DLLVM_TABLEGEN={}'.format(
        os.path.join( tblgen_root, 'bin', 'llvm-tblgen' ) ),
      '-DCLANG_TABLEGEN={}'.format(
        os.path.join( tblgen_root, 'bin', 'clang-tblgen' ) ),
      '-DLLVM_TARGET_ARCH={}'.format( target_architecture ),
      '-DLLVM_INCLUDE_EXAMPLES=OFF',
      '-DLLVM_INCLUDE_TESTS=OFF',
      '-DLLVM_INCLUDE_DOCS=OFF',
      '-DLLVM_ENABLE_TERMINFO=OFF',
      '-DLLVM_ENABLE_ZLIB=OFF',
      '-DLLVM_ENABLE_LIBEDIT=OFF',
      '-DLLVM_ENABLE_LIBXML2=OFF',
      '-DLLVM_ENABLE_ZSTD=OFF',
      *GetCacheArgs( build_dir ),
      os.path.join( llvm_source_dir, 'llvm' )
    ]
    if target != host: # We're cross compilinging and need a toolchain file.
      toolchain_file = os.path.join( DIR_OF_THIS_SCRIPT,
                                     'toolchain_files',
                                     target + '.cmake' )
      if os.path.exists( toolchain_file ):
        cmake_configure_args.append(
          '-DCMAKE_TOOLCHAIN_FILE={}'.format( toolchain_file ) )
      else:
        print( "WARNING: Cross compiling, but no toolchain file found for " +
               toolchain_file )
        sys.exit( 1 )

    print( 'CMake Args: {}'.format( ' '.join( cmake_configure_args ) ) )

    subprocess.check_call( cmake_configure_args )

    subprocess.check_call( [
      cmake,
      '--build', '.',
      '--parallel',
      GetLogicalCores(),
      '--target', 'install' ] )


def BuildTableGen( build_dir, llvm_source_dir ):
  with WorkingDirectory( build_dir ):
    cmake = shutil.which( 'cmake' )
    subprocess.check_call( [
      cmake,
      *GetGeneratorArgs(),
      '-DCMAKE_BUILD_TYPE=Release',
      '-DLLVM_ENABLE_PROJECTS=clang',
      *GetCacheArgs( build_dir ),
      os.path.join( llvm_source_dir, 'llvm' ) ] )

    subprocess.check_call( [
      cmake,
      '--build', '.',
      '--parallel',
      GetLogicalCores(),
      '--target', 'llvm-tblgen', 'clang-tblgen' ] )


def CheckDependencies( name, path, versions ):
  dependencies = []
  objdump = shutil.which( 'objdump' )
  output = subprocess.check_output(
      [ objdump, '-p', path ],
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

  print( 'Minimum versions required:' )
  for library, values in versions.items():
    print( library + ' ' + str( max( values ) ) )


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
  # Uploading large assets via raw requests to the GitHub API is prone to
  # obscure failures (e.g. "Validation Failed") when multiple parallel matrix
  # jobs race to create the same release, or due to TLS/connection issues with
  # large streamed uploads. The `gh` CLI, preinstalled on GitHub-hosted
  # runners, handles both problems: `gh release create` is idempotent (we
  # tolerate it failing when another job already created the release) and
  # `gh release upload --clobber` replaces an existing asset atomically.
  bundle_version = GetBundleVersion( args )
  bundle_name = os.path.basename( bundle_path )
  repo = '{}/llvm'.format( args.gh_org )
  env = os.environ.copy()
  env[ 'GH_TOKEN' ] = args.gh_token

  prerelease = args.release_candidate is not None
  name = 'LLVM and Clang ' + args.version
  if args.release_candidate:
    name += ' RC' + str( args.release_candidate )
  notes = name + ' without realtime, terminfo, and zlib dependencies.'

  # Multiple parallel jobs race to create the same release. Tolerate failure
  # here; we verify the release exists before uploading.
  print( 'Releasing {} on GitHub.'.format( bundle_version ) )
  create_cmd = [
    'gh', 'release', 'create', bundle_version,
    '--repo', repo,
    '--title', name,
    '--notes', notes,
  ]
  if prerelease:
    create_cmd.append( '--prerelease' )

  result = subprocess.run( create_cmd, env = env )
  if result.returncode != 0:
    check = subprocess.run(
      [ 'gh', 'release', 'view', bundle_version, '--repo', repo ],
      env = env,
      stdout = subprocess.DEVNULL,
      stderr = subprocess.DEVNULL,
    )
    if check.returncode != 0:
      sys.exit( 'Failed to create or find release {}.'.format(
        bundle_version ) )
    print( 'Release {} already exists.'.format( bundle_version ) )

  print( 'Uploading {} on GitHub.'.format( bundle_name ) )
  try:
    subprocess.run(
      [ 'gh', 'release', 'upload', bundle_version, bundle_path,
        '--repo', repo, '--clobber' ],
      env = env,
      check = True,
    )
  except subprocess.CalledProcessError as e:
    sys.exit( 'Uploading failed: {}'.format( e ) )


def ParseArguments():
  parser = argparse.ArgumentParser()
  parser.add_argument( 'version', type = str, help = 'LLVM version.' )
  parser.add_argument( '--release-candidate', type = int,
                       help = 'LLVM release candidate number.' )

  parser.add_argument( '--no-upload', action = 'store_true',
                       help = "Don't upload the archive to GitHub." )

  parser.add_argument( '--gh-token', action='store',
                       help = 'GitHub api token. Defaults to environment '
                              'variable: GITHUB_TOKEN.' )
  parser.add_argument( '--gh-org', action='store',
                       default = 'ycm-core',
                       help = 'GitHub organization to which '
                              'the archive will be uploaded to. ' )

  parser.add_argument( '--base-dir', action='store', help='Working dir',
                       default = DIR_OF_THIS_SCRIPT )

  parser.add_argument( '--target-architecture',
                       action='store',
                       help='For cross-compiling',
                       default=platform.machine() )

  args = parser.parse_args()

  if not args.no_upload:
    if not args.gh_token:
      if 'GITHUB_TOKEN' not in os.environ:
        sys.exit( 'ERROR: Must specify either --gh-token or '
                  'GITHUB_TOKEN in environment' )
      args.gh_token = os.environ[ 'GITHUB_TOKEN' ]

  return args


def Main():
  args = ParseArguments()
  base_dir = os.path.join(
    os.path.abspath( args.base_dir ),
    ENV_DATA[ platform.system() ][ args.target_architecture ][ 'target' ] )
  if not os.path.isdir( base_dir ):
    os.mkdir( base_dir )

  llvm_url = GetLlvmBaseUrl( args )
  llvm_version = GetLlvmVersion( args )
  llvm_source = LLVM_SOURCE.format( version = llvm_version )
  llvm_source_dir = os.path.join( base_dir, llvm_source )

  if not os.path.exists( llvm_source_dir ):
    with WorkingDirectory( base_dir ):
      DownloadSource( llvm_url, llvm_source )

  tblgen_build_dir = os.path.join( base_dir, 'tblgen_build' )
  llvm_build_dir = os.path.join( base_dir, 'llvm_build' )
  llvm_install_dir = os.path.join( base_dir, 'llvm_install' )

  if not os.path.exists( tblgen_build_dir ):
    os.mkdir( tblgen_build_dir )
  if not os.path.exists( llvm_build_dir ):
    os.mkdir( llvm_build_dir )
  if not os.path.exists( llvm_install_dir ):
    os.mkdir( llvm_install_dir )

  BuildTableGen( tblgen_build_dir, llvm_source_dir )
  BuildLlvm( llvm_build_dir,
             llvm_install_dir,
             llvm_source_dir,
             tblgen_build_dir,
             args.target_architecture )

  if platform.system() == 'Linux':
    CheckLlvm( llvm_install_dir )

  target = ENV_DATA[ platform.system() ][ args.target_architecture ][
    'archive' ]
  bundle_version = GetBundleVersion( args )
  bundle_name = BUNDLE_NAME.format( version = bundle_version, target = target )
  archive_name = bundle_name + '.tar.xz'
  bundle_path = os.path.join( base_dir, archive_name )
  if not os.path.exists( bundle_path ):
    with WorkingDirectory( base_dir ):
      BundleLlvm( bundle_name, archive_name, llvm_install_dir, bundle_version )

  if not args.no_upload:
    UploadLlvm( args, bundle_path )


if __name__ == "__main__":
  Main()
