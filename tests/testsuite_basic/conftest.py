# MIT License
#
# Copyright (c) 2018-2019 Red Hat, Inc.

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import datetime
import shutil
import subprocess
from pathlib import Path
from typing import Tuple, Iterator

import pytest
from flexmock import flexmock
from gnupg import GPG

from ogr.abstract import PullRequest, PRStatus
from ogr.services.github import GithubService, GithubProject
from ogr.services.pagure import PagureProject, PagureService, PagureUser
from packit.api import PackitAPI
from packit.cli.utils import get_packit_api
from packit.config import get_local_package_config
from packit.distgit import DistGit
from packit.fedpkg import FedPKG
from packit.specfile import Specfile
from packit.local_project import LocalProject
from packit.upstream import Upstream
from packit.utils import cwd
from tests.testsuite_basic.spellbook import (
    prepare_dist_git_repo,
    get_test_config,
    SOURCEGIT_UPSTREAM,
    SOURCEGIT_SOURCEGIT,
    git_add_and_commit,
    TARBALL_NAME,
    UPSTREAM,
    initiate_git_repo,
    DISTGIT,
    DG_OGR,
)
from tests.testsuite_basic.utils import remove_gpg_key_pair

DOWNSTREAM_PROJECT_URL = "https://src.fedoraproject.org/not/set.git"
UPSTREAM_PROJECT_URL = "https://github.com/also-not/set.git"


@pytest.fixture()
def mock_downstream_remote_functionality(downstream_n_distgit):
    u, d = downstream_n_distgit

    dglp = LocalProject(
        working_dir=str(d),
        git_url="https://packit.dev/rpms/beer",
        git_service=PagureService(),
    )

    flexmock(DistGit, update_branch=lambda *args, **kwargs: "0.0.0", local_project=dglp)

    mock_spec_download_remote_s(d)

    pc = get_local_package_config(str(u))
    pc.dist_git_clone_path = str(d)
    pc.upstream_project_url = str(u)
    return u, d


@pytest.fixture()
def mock_remote_functionality_upstream(upstream_and_remote, distgit_and_remote):
    u, _ = upstream_and_remote
    d, _ = distgit_and_remote
    return mock_remote_functionality(d, u)


@pytest.fixture()
def mock_remote_functionality_sourcegit(sourcegit_and_remote, distgit_and_remote):
    sourcegit, _ = sourcegit_and_remote
    distgit, _ = distgit_and_remote
    return mock_remote_functionality(upstream=sourcegit, distgit=distgit)


def mock_spec_download_remote_s(path: Path):
    def mock_download_remote_sources():
        """ mock download of the remote archive and place it into dist-git repo """
        tarball_path = path / TARBALL_NAME
        hops_filename = "hops"
        hops_path = path / hops_filename
        hops_path.write_text("Cascade\n")
        subprocess.check_call(
            ["tar", "-cf", str(tarball_path), hops_filename], cwd=path
        )

    flexmock(Specfile, download_remote_sources=mock_download_remote_sources)


def mock_remote_functionality(distgit: Path, upstream: Path):
    def mocked_pr_create(*args, **kwargs):
        return PullRequest(
            title="",
            id=42,
            status=PRStatus.open,
            url="",
            description="",
            author="",
            source_branch="",
            target_branch="",
            created=datetime.datetime(1969, 11, 11, 11, 11, 11, 11),
        )

    flexmock(GithubService)
    github_service = GithubService()
    flexmock(
        GithubService,
        get_project=lambda repo, namespace: GithubProject(
            "also-not", github_service, "set", github_repo=flexmock()
        ),
    )
    flexmock(
        PagureProject,
        get_git_urls=lambda: {"git": DOWNSTREAM_PROJECT_URL},
        fork_create=lambda: None,
        get_fork=lambda: PagureProject("", "", PagureService()),
        pr_create=mocked_pr_create,
    )
    flexmock(
        GithubProject,
        get_git_urls=lambda: {"git": UPSTREAM_PROJECT_URL},
        fork_create=lambda: None,
    )
    flexmock(PagureUser, get_username=lambda: "packito")

    mock_spec_download_remote_s(distgit)

    dglp = LocalProject(
        working_dir=str(distgit),
        git_url="https://packit.dev/rpms/beer",
        git_service=PagureService(),
    )
    flexmock(
        DistGit,
        push_to_fork=lambda *args, **kwargs: None,
        # let's not hammer the production lookaside cache webserver
        is_archive_in_lookaside_cache=lambda archive_path: False,
        local_project=dglp,
    )

    def mocked_new_sources(sources=None):
        if not Path(sources).is_file():
            raise RuntimeError("archive does not exist")

    flexmock(FedPKG, init_ticket=lambda x=None: None, new_sources=mocked_new_sources)
    pc = get_local_package_config(str(upstream))
    pc.dist_git_clone_path = str(distgit)
    pc.upstream_project_url = str(upstream)
    return upstream, distgit


@pytest.fixture()
def mock_patching():
    flexmock(Upstream).should_receive("create_patches").and_return(["patches"])
    flexmock(DistGit).should_receive("add_patches_to_specfile").with_args(["patches"])


@pytest.fixture()
def upstream_and_remote(tmpdir) -> Tuple[Path, Path]:
    t = Path(str(tmpdir))

    u_remote_path = t / "upstream_remote"
    u_remote_path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "--bare", "."], cwd=u_remote_path)

    u = t / "upstream_git"
    shutil.copytree(UPSTREAM, u)
    initiate_git_repo(u, tag="0.1.0", push=True, upstream_remote=str(u_remote_path))

    return u, u_remote_path


@pytest.fixture()
def cwd_upstream(upstream_and_remote) -> Iterator[Path]:
    upstream, _ = upstream_and_remote
    with cwd(str(upstream)):
        yield upstream


@pytest.fixture()
def distgit_and_remote(tmpdir) -> Tuple[Path, Path]:
    t = Path(str(tmpdir))

    d_remote_path = t / "dist_git_remote"
    d_remote_path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "--bare", "."], cwd=d_remote_path)

    d = t / "dist_git"
    shutil.copytree(DISTGIT, d)
    initiate_git_repo(
        d,
        push=True,
        remotes=[
            ("origin", str(d_remote_path)),
            ("i_am_distgit", "https://src.fedoraproject.org/rpms/python-ogr"),
        ],
    )
    prepare_dist_git_repo(d)

    return d, d_remote_path


@pytest.fixture()
def ogr_distgit_and_remote(tmpdir) -> Tuple[Path, Path]:
    temp_dir = Path(str(tmpdir))

    d_remote_path = temp_dir / "ogr_dist_git_remote"
    d_remote_path.mkdir(parents=True, exist_ok=True)
    subprocess.check_call(["git", "init", "--bare", "."], cwd=d_remote_path)

    d = temp_dir / "ogr_dist_git"
    shutil.copytree(DG_OGR, d)
    initiate_git_repo(
        d,
        push=True,
        remotes=[
            ("origin", str(d_remote_path)),
            ("i_am_distgit", "https://src.fedoraproject.org/rpms/python-ogr"),
        ],
    )
    prepare_dist_git_repo(d)
    return d, d_remote_path


@pytest.fixture()
def sourcegit_and_remote(tmpdir):
    temp_dir = Path(str(tmpdir))

    sourcegit_remote = temp_dir / "source_git_remote"
    sourcegit_remote.mkdir()
    subprocess.check_call(["git", "init", "--bare", "."], cwd=sourcegit_remote)

    sourcegit_dir = temp_dir / "source_git"
    shutil.copytree(SOURCEGIT_UPSTREAM, sourcegit_dir)
    initiate_git_repo(sourcegit_dir, tag="0.1.0")
    subprocess.check_call(
        ["cp", "-R", SOURCEGIT_SOURCEGIT, temp_dir], cwd=sourcegit_remote
    )
    git_add_and_commit(directory=sourcegit_dir, message="sourcegit content")

    return sourcegit_dir, sourcegit_remote


@pytest.fixture()
def downstream_n_distgit(tmpdir):
    t = Path(str(tmpdir))

    d_remote = t / "downstream_remote"
    d_remote.mkdir()
    subprocess.check_call(["git", "init", "--bare", "."], cwd=d_remote)

    d = t / "dist_git"
    shutil.copytree(DISTGIT, d)
    initiate_git_repo(d, tag="0.0.0")

    u = t / "upstream_git"
    shutil.copytree(UPSTREAM, u)
    initiate_git_repo(u, push=False, upstream_remote=str(d_remote))

    return u, d


@pytest.fixture()
def upstream_instance(upstream_and_remote, distgit_and_remote, tmpdir):
    with cwd(tmpdir):
        u, _ = upstream_and_remote
        d, _ = distgit_and_remote
        c = get_test_config()

        pc = get_local_package_config(str(u))
        pc.upstream_project_url = str(u)
        pc.dist_git_clone_path = str(d)
        lp = LocalProject(working_dir=str(u))

        ups = Upstream(c, pc, lp)
        yield u, ups


@pytest.fixture()
def upstream_instance_with_two_commits(upstream_instance):
    u, ups = upstream_instance
    new_file = u / "new.file"
    new_file.write_text("Some content")
    git_add_and_commit(u, message="Add new file")
    return u, ups


@pytest.fixture()
def distgit_instance(
    upstream_and_remote, distgit_and_remote, mock_remote_functionality_upstream
):
    u, _ = upstream_and_remote
    d, _ = distgit_and_remote
    c = get_test_config()
    pc = get_local_package_config(str(u))
    pc.dist_git_clone_path = str(d)
    pc.upstream_project_url = str(u)
    dg = DistGit(c, pc)
    return d, dg


@pytest.fixture()
def api_instance(upstream_and_remote, distgit_and_remote):
    u, _ = upstream_and_remote
    d, _ = distgit_and_remote

    c = get_test_config()
    api = get_packit_api(
        config=c, local_project=LocalProject(working_dir=str(Path.cwd()))
    )
    return u, d, api


@pytest.fixture()
def api_instance_source_git(sourcegit_and_remote, distgit_and_remote):
    sourcegit, _ = sourcegit_and_remote
    distgit, _ = distgit_and_remote
    with cwd(sourcegit):
        c = get_test_config()
        pc = get_local_package_config(str(sourcegit))
        pc.upstream_project_url = str(sourcegit)
        pc.dist_git_clone_path = str(distgit)
        up_lp = LocalProject(working_dir=str(sourcegit))
        api = PackitAPI(c, pc, up_lp)
        return api


@pytest.fixture()
def gnupg_instance() -> GPG:
    return GPG()


@pytest.fixture()
def private_gpg_key() -> str:
    """
    gnupg_instance.export_keys(key.fingerprint, secret=True, expect_passphrase=False)
    """

    return """-----BEGIN PGP PRIVATE KEY BLOCK-----

lQOYBFzRgy8BCADbrsCtPWqVWTNkl3U1LK3YWLnKiZIIMELv305s6Lfj8lTtFlAT
GXuIfalAqN18Rv6h+/aMXW872Gwk6Iv9hdkSF9e04YGqdrr7H/rw8976NogvhR73
aTi1BGh43AtFWifJy/MaSCVfy2gTeYqK17FHDnzqGunwQ4L0PQMvkscMOgmCQlPj
qF2WWiknku/aMeIoqAjUfIV3/dKVYPJH7g4QTo8U00CvfLSFMFhgzxW/nC+fPOh6
h7jXnXk2xvo+9rWPrPplUtjjuufjzxvz/azlB3PIR05tTRU27P2xI4rJBkZdzZ6t
67obFxImpRVJtV3kvyBPAja4k7x/mWQvC/dBABEBAAEAB/kB8DWKgcV4OmCB9XUn
CjUheMzw3MxhTp20lJ2SR+5hcECwE9eSh5HHt0YgSC0mHNE/2COJgwSJfGQd4kBj
9QOgjX3NfoTgnmoRb6uM5zXzMrp6YtwOVksWC8spL9XYn45E0UwckgDkarzJGTQv
++24QQg4n5KrWEkmQwiNaafgc3lyFf+xaCri2xlwMYdFqltROzrckHkcbjYFdASr
2dqoxGn79OdRhndg8+n1FA2UpQhI4fZyvQwkfO7x1Mjl3DxH97K6cvnW+KI0IlhE
2laZRowzqn8q8+zopWtFkhQmD/SV43eLfCbzyb0KKyAheH8zD6DS7Ij/KkcnLmTt
pMzxBADb0DkUb/mAArhzBDf4QBup+ryhuae9cPkhMlVKiegtojlmmsdTKgCxybFH
M33ITeNx84IvDTZCZkHFwyFWVXLTbQyIt7RsGOEYxbt7cI+SgmtvEdYtnf6Y1H7F
0WksC8ES4Z6BToQ4qeI5rd3QAk+qmQ4ZSA9iT7vDG8/9Wv0TKQQA/9kFB318C39+
m1W6m9/B482brEJqrGaAkFT4yOSjeo1C+n3b/iedCROwP44L1ifZT83uJ3ad/o/f
N5iDHiXjASVnIuuehLjuwrauZhkhiOcjRyLRtrDweF5NDQu70o69ON3j4fWebhmT
OFxfGaD9lkWuM2Lf0/0kbErc8X31nlkD/2tTepbT6y1ud2OrI9Fw4E8eKnSycJwW
JitKqllXkpugaEihBtpAf7zcarchnF2FIqnYuT5nVZ067lPKU5rRMuD3D+IXUxSy
aNgCSzVMX2t43DQcyZ35kqgLYOJwdc78tNtkNvbTkZBRDTpcdK69M6L+x+wMsHb1
PpLui3F4WAQ/Q2O0IUF1dG9nZW5lcmF0ZWQgS2V5IDxwYWNraXRAcGFja2l0PokB
TgQTAQgAOBYhBFvV9i+3z2ur7IY5eKtE1ItYjzIoBQJc0YMvAhsvBQsJCAcCBhUK
CQgLAgQWAgMBAh4BAheAAAoJEKtE1ItYjzIoaIQH/RQ47hZhyGz9vgD196KIUwTp
WLrJPVxNSd4mqx0lwE3B5T8xyboZHZoD5gNxFR/6CPs2Nh4fiyqjKzeU/t5W4Y3c
evyhgBJu9y4K1s7HHf+Sby0jlaeQyVs11Ngoul+CM2m6ZzlLyexEC8dUZ9fclDxb
TOQH3GkJ24vdkbZwN+KdL/AYtbRAvE2BwfK0EMg7ibRoh9Zfpc2hYLjBZ83yAKgY
FZ8bkeRu7lTdzpbTu/nEFKKDYusgbJuLBaW3GEjj726C/IHAp16QZI/SPKpt0cAK
YEWYFA0MxyZQhRqEDH2whr+QyWr5155N7kzHnUxbwos66sfcCmCH7iZHbN7q828=
=RSyl
-----END PGP PRIVATE KEY BLOCK-----
"""


@pytest.fixture()
def gnupg_key_fingerprint(gnupg_instance: GPG, private_gpg_key: str):
    keys_imported = gnupg_instance.import_keys(private_gpg_key)
    key_fingerprint = keys_imported.fingerprints[0]
    yield key_fingerprint

    if key_fingerprint in gnupg_instance.list_keys(secret=True).fingerprints:
        remove_gpg_key_pair(
            gpg_binary=gnupg_instance.gpgbinary, fingerprint=key_fingerprint
        )


@pytest.fixture()
def upstream_without_config(tmpdir):
    t = Path(str(tmpdir))

    u_remote = t / "upstream_remote"
    u_remote.mkdir()
    subprocess.check_call(["git", "init", "--bare", "."], cwd=u_remote)

    return u_remote


@pytest.fixture(params=["upstream", "distgit", "ogr-distgit"])
def cwd_upstream_or_distgit(
    request, upstream_and_remote, distgit_and_remote, ogr_distgit_and_remote
):
    """
    Run the code from upstream, downstream and ogr-distgit.

    When using be careful to
        - specify this fixture in the right place
        (the order of the parameters means order of the execution)
        - to not overwrite the cwd in the other fixture or in the test itself
    """
    cwd_path = {
        "upstream": upstream_and_remote[0],
        "distgit": distgit_and_remote[0],
        "ogr-distgit": ogr_distgit_and_remote[0],
    }[request.param]

    with cwd(cwd_path):
        yield cwd_path


@pytest.fixture(params=["upstream", "ogr-distgit"])
def upstream_or_distgit_path(
    request, upstream_and_remote, distgit_and_remote, ogr_distgit_and_remote
):
    """
    Parametrize the test to upstream, downstream [currently skipped] and ogr distgit
    """
    cwd_path = {
        "upstream": upstream_and_remote[0],
        "distgit": distgit_and_remote[0],
        "ogr-distgit": ogr_distgit_and_remote[0],
    }[request.param]

    return cwd_path
