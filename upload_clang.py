#!/usr/bin/env python3

import argparse
import contextlib
import json
import lzma
import os
import os.path as p
import platform
import shutil
import subprocess
import sys
import tempfile
import tarfile
import hashlib
from distutils.spawn import find_executable


DIR_OF_THIS_SCRIPT = p.dirname( p.abspath( __file__ ) )
DIR_OF_THIRD_PARTY = p.join( DIR_OF_THIS_SCRIPT, 'third_party' )


import urllib.error
import urllib.request
from io import BytesIO


def OnWindows():
  return platform.system() == 'Windows'


def OnMac():
  return platform.system() == 'Darwin'


LLVM_DOWNLOAD_DATA = {
  'win32': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'nsis',
    'llvm_package': 'LLVM-{llvm_version}-{os_name}.exe',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd.exe' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'libclang.dll' ),
        os.path.join( 'lib', 'libclang.lib' ),
      ]
    }
  },
  'win64': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'nsis',
    'llvm_package': 'LLVM-{llvm_version}-{os_name}.exe',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd.exe' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'libclang.dll' ),
        os.path.join( 'lib', 'libclang.lib' ),
      ]
    }
  },
  'x86_64-apple-darwin': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.dylib' ),
      ],
    }
  },
  'x86_64-unknown-linux-gnu': {
    'url': ( 'https://github.com/ycm-core/llvm/'
             'releases/download/{llvm_version}/{llvm_package}' ),
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.so' ),
        os.path.join( 'lib', 'libclang.so.{llvm_version:.2}' )
      ]
    }
  },
  'i386-unknown-freebsd11': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.so' ),
        os.path.join( 'lib', 'libclang.so.{llvm_version:.2}' )
      ]
    }
  },
  'amd64-unknown-freebsd11': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.so' ),
        os.path.join( 'lib', 'libclang.so.{llvm_version:.2}' )
      ]
    }
  },
  'aarch64-linux-gnu': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.so' ),
        os.path.join( 'lib', 'libclang.so.{llvm_version:.2}' )
      ]
    }
  },
  'armv7a-linux-gnueabihf': {
    'url': 'https://github.com/llvm/llvm-project/releases/download/'
           'llvmorg-{llvm_version}/{llvm_package}',
    'format': 'lzma',
    'llvm_package': 'clang+llvm-{llvm_version}-{os_name}.tar.xz',
    'clangd_package': {
      'name': 'clangd-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'bin', 'clangd' ),
      ]
    },
    'libclang_package': {
      'name': 'libclang-{llvm_version}-{os_name}.tar.bz2',
      'files_to_copy': [
        os.path.join( 'lib', 'libclang.so' ),
        os.path.join( 'lib', 'libclang.so.{llvm_version:.2}' )
      ]
    }
  },
}


@contextlib.contextmanager
def TemporaryDirectory( keep_temp ):
  temp_dir = tempfile.mkdtemp()
  try:
    yield temp_dir
  finally:
    if keep_temp:
      print( f"*** Please delete temp dir: {temp_dir}" )
    else:
      shutil.rmtree( temp_dir )


def DownloadClangLicense( version, destination ):
  print( 'Downloading license...' )
  file_name = os.path.join( destination, 'LICENSE.TXT' )
  with urllib.request.urlopen(
      f'https://releases.llvm.org/{ version }/LICENSE.TXT' ) as response:

    with open( file_name, 'wb' ) as f:
      f.write( response.read() )

  return file_name


def Download( url ):
  print( f'Downloading { url.rsplit( "/", 1 )[ -1 ] }' )
  with urllib.request.urlopen( url ) as response:
    return response.read()


def ExtractTar( uncompressed_data, destination ):
  with tarfile.TarFile( fileobj=uncompressed_data, mode='r' ) as tar_file:
    a_member = tar_file.getmembers()[ 0 ]
    tar_file.extractall( destination )

  # Determine the directory name
  return os.path.join( destination, a_member.name.split( '/' )[ 0 ] )


def ExtractLZMA( compressed_data, destination ):
  uncompressed_data = BytesIO( lzma.decompress( compressed_data ) )
  return ExtractTar( uncompressed_data, destination )


def Extract7Z( llvm_package, archive, destination ):
  # Extract with appropriate tool
  if OnWindows():
    import winreg

    with winreg.OpenKey( winreg.HKEY_LOCAL_MACHINE, 'SOFTWARE\\7-Zip' ) as key:
      executable = os.path.join( winreg.QueryValueEx( key, "Path" )[ 0 ],
                                '7z.exe' )
  elif OnMac():
    # p7zip is available from homebrew (brew install p7zip)
    executable = find_executable( '7z' )
  else:
    # On Linux, p7zip 16.02 is required.
    executable = find_executable( '7z' )

  command = [
    executable,
    '-y',
    'x',
    archive,
    '-o' + destination
  ]

  # Silence 7-Zip output.
  subprocess.check_call( command, stdout = subprocess.PIPE )

  return destination


def MakeBundle( files_to_copy,
                license_file_name,
                source_dir,
                bundle_file_name,
                hashes,
                version ):
  archive_name = os.path.basename( bundle_file_name )
  print( f'Bundling files to { archive_name }' )
  with tarfile.open( name=bundle_file_name, mode='w:bz2' ) as tar_file:
    tar_file.add( license_file_name, arcname='LICENSE.TXT' )
    for item in files_to_copy:
      source_file_name = item.format( llvm_version = version )
      target_file_name = source_file_name

      name = os.path.join( source_dir, source_file_name )
      if not os.path.exists( name ):
        raise RuntimeError( f'File {name} does not exist.' )
      tar_file.add( name = name, arcname = target_file_name )

  sys.stdout.write( 'Calculating checksum: ' )
  with open( bundle_file_name, 'rb' ) as f:
    hashes[ archive_name ] = hashlib.sha256( f.read() ).hexdigest()
    print( hashes[ archive_name ] )


def UploadBundleToGithub( user_name,
                          api_token,
                          org,
                          os_name,
                          version,
                          bundle_file_name ):
  upload_url = None
  try:
    response = urllib.request.urlopen(
      f'https://api.github.com/repos/{org}/llvm/releases' )
    response_json = json.loads( response.read() )
    response.close()
    for release in response_json:
      if release[ 'tag_name' ] != version:
        continue
    upload_url = release[ 'upload_url' ].replace( '{?name,label}', '' )
    upload_url += '?name=' + os.path.split( bundle_file_name )[ 1 ]
  except urllib.error.URLError as e:
    message = response.json()[ 'message' ]
    sys.exit( f'Getting releases failed with message: { e.fp.read() }' )
    e.close()


  if upload_url is None:
    os.exit( f'Version { version } not published. '
             'Run package_llvm.py in llvm repo first.' )
  print( 'Uploading to github...' )
  repo = bundle_file_name[ : bundle_file_name.find( '-' ) ]
  with open( bundle_file_name, 'rb' ) as bundle:
    request = urllib.request.Request(
      upload_url,
      data = bundle,
      headers = { 'Content-Type': 'application/x-xz' },
      method = 'POST' )
    auth_handler = urllib.request.HTTPBasicAuthHandler()
    auth_handler.add_password( None,
                               'https://api.github.com/',
                               user_name,
                               api_token )
    opener = urllib.request.build_opener( auth_handler )
    request = opener.open( request )
    request.close()


def ParseArguments():
  parser = argparse.ArgumentParser()

  parser.add_argument( 'version', action='store',
                       help = 'The LLVM version' )

  parser.add_argument( '--gh-user', action='store',
                       help = 'GitHub user name. Defaults to environment '
                              'variable: GITHUB_USERNAME' )
  parser.add_argument( '--gh-token', action='store',
                       help = 'GitHub api token. Defaults to environment '
                              'variable: GITHUB_TOKEN.' )
  parser.add_argument( '--gh-org', action='store',
                       default = 'bstaletic',
                       help = 'GitHub organization to which '
                              'the archive will be uploaded to. ' )
  parser.add_argument( '--from-cache', action='store',
                       help = 'Use the clang packages from this dir. Useful '
                              'if releases.llvm.org is unreliable.' )
  parser.add_argument( '--output-dir', action='store',
                       help = 'For testing, directory to put bundles in.' )
  parser.add_argument( '--no-upload', action='store_true',
                       help = "For testing, just build the bundles; don't "
                              "upload to github. Useful with --output-dir." )
  parser.add_argument( '--keep-temp', action='store_true',
                       help = "For testing, don't delete the temp dir" )

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


def PrepareBundleBuiltIn( extract_fun,
                          cache_dir,
                          llvm_package,
                          download_url,
                          temp_dir ):
  package_dir = None
  if cache_dir:
    archive = os.path.join( cache_dir, llvm_package )
    print( f'Extracting cached {llvm_package}' )
    try:
      with open( archive, 'rb' ) as f:
        package_dir = extract_fun( f.read(), temp_dir )
    except IOError:
      pass

  if not package_dir:
    compressed_data = Download( download_url )
    if cache_dir:
      try:
        archive = os.path.join( cache_dir, llvm_package )
        with open( archive, 'wb' ) as f:
          f.write( compressed_data )
      except IOError as e:
        print( f"Unable to write cache file: {e.message}" )
        pass

    print( f'Extracting {llvm_package}' )
    package_dir = extract_fun( compressed_data, temp_dir )

  return package_dir


def PrepareBundleLZMA( cache_dir, llvm_package, download_url, temp_dir ):
  return PrepareBundleBuiltIn( ExtractLZMA,
                               cache_dir,
                               llvm_package,
                               download_url,
                               temp_dir )


def PrepareBundleNSIS( cache_dir, llvm_package, download_url, temp_dir ):
  archive = None
  if cache_dir:
    archive = os.path.join( cache_dir, llvm_package )
    if os.path.exists( archive ):
      print( f'Extracting cached {llvm_package}' )
    else:
      archive = None

  if not archive:
    compressed_data = Download( download_url )
    dest_dir = cache_dir if cache_dir else temp_dir
    archive = os.path.join( dest_dir, llvm_package )
    with open( archive, 'wb' ) as f:
      f.write( compressed_data )
    print( f'Extracting {llvm_package}' )

  return Extract7Z( llvm_package, archive, temp_dir )


def BundleAndUpload( args, temp_dir, output_dir, os_name, download_data,
                     license_file_name, hashes ):
  llvm_package = download_data[ 'llvm_package' ].format(
    os_name = os_name,
    llvm_version = args.version )
  download_url = download_data[ 'url' ].format( llvm_version = args.version,
                                                llvm_package = llvm_package )

  temp_dir = os.path.join( temp_dir, os_name )
  os.makedirs( temp_dir )

  try:
    if download_data[ 'format' ] == 'lzma':
      package_dir = PrepareBundleLZMA( args.from_cache,
                                       llvm_package,
                                       download_url,
                                       temp_dir )
    elif download_data[ 'format' ] == 'nsis':
      package_dir = PrepareBundleNSIS( args.from_cache,
                                       llvm_package,
                                       download_url,
                                       temp_dir )
    else:
      raise AssertionError( 'Format not yet implemented: {}'.format(
        download_data[ 'format' ] ) )
  except urllib.error.HTTPError as error:
    if error.code != 404:
      raise
    print( f'Cannot download {llvm_package}' )
    return

  for binary in [ 'libclang', 'clangd' ]:
    package_name = binary + '_package'
    archive_name = download_data[ package_name ][ 'name' ].format(
      os_name = os_name,
      llvm_version = args.version )
    archive_path = os.path.join( output_dir, archive_name )

    MakeBundle( download_data[ package_name ][ 'files_to_copy' ],
                license_file_name,
                package_dir,
                archive_path,
                hashes,
                args.version )

    if not args.no_upload:
      UploadBundleToGithub( args.gh_user,
                            args.gh_token,
                            args.gh_org,
                            os_name,
                            args.version,
                            archive_path )


def Overwrite( src, dest ):
  if os.path.exists( dest ):
    shutil.rmtree( dest )
  shutil.copytree( src, dest )


def Main():
  args = ParseArguments()

  output_dir = args.output_dir if args.output_dir else tempfile.mkdtemp()

  try:
    hashes = {}
    with TemporaryDirectory( args.keep_temp ) as temp_dir:
      license_file_name = DownloadClangLicense( args.version, temp_dir )
      for os_name, download_data in LLVM_DOWNLOAD_DATA.items():
        BundleAndUpload( args, temp_dir, output_dir, os_name, download_data,
                         license_file_name, hashes )
  finally:
    if not args.output_dir:
      shutil.rmtree( output_dir )

  for bundle_file_name, sha256 in hashes.items():
    print( f'Checksum for {bundle_file_name}: {sha256}' )


if __name__ == "__main__":
  Main()
