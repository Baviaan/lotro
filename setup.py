from setuptools import setup
import re

requirements = []
with open('requirements.txt') as f:
    requirements = f.read().splitlines()

version = ""
with open('source/__init__.py') as f:
    version = re.search(r'^__version__\s*=\s*[\'"]([^\'"]*)[\'"]', f.read(), re.MULTILINE).group(1)

if not version:
    raise RuntimeError("Version is not set.")

readme = ""
with open('README.md') as f:
    readme = f.read()

setup(
    name="Saruman",
    version=version,
    author="Baviaan",
    url="https://github.com/Baviaan/lotro",
    license="GPLv3",
    description="A discord bot for scheduling raids."
    long_description=readme,
    include_package_data=True,
    install_requires=requirements,
    python_requires='>=3.8',
)
