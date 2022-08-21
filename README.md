# YCM libclang and clangd packages

This repository contains the minimal libclang and clangd packages used by
YouCompleteMe's ycmd server.

The whole llvm+clang pacakge is huge, but ycmd only needs libclang (and/or
clangd), so this minimises installation size for users.

In addition, upstream binaries are reliant on some libraries (like ncurses)
which aren't always available on user systems and are not necessary just for
libclang and/or clangd, so on those platforms, we actually build our own
versions using Github Actions.

Finally, upstream packages aren't available for some supported architectures
(e.g. Apple silicon), so we build those ourselves too.

# Packaging a new release

There are 2 steps:

1. Build, package and upload clang+llvm for those architectures which we are
   building ourselves (currently various linux and apple m1). This is the GitHub
   Action "pacakge llvm". It's triggered manually by maintainers, passing the
   LLVM version (e.g. "14.0.0"). It takes ages.
2. Repackage just libclang and clangd bundles and upload them as github
   releases. Again, triggered manually by maintainers, again passing the LLVM
   version (e.g. "14.0.0"). This is fiarly quick. It just downloads the bundles,
   pulls out the bits we need, grabs the LICENSE and re-uploads the minimal
   pacakges.

Once that's all done, we can update `build.py` in ycmd to pull the new package
version from this repo, and run `update_clangd_headers.py` to update the
libclang support headers.

# Maintenance

Sometimes the paths to the dependencies change, so we have to update
`pacakge_llvm.py` and/or `upload_clang.py` to fix up paths/versions etc.

But in general, the above workflows should _just work_ hopefully. In the past we
had to run these things locally on appropriate hardware and upload with our own
keys, but GHA should make that no longer necessary.
