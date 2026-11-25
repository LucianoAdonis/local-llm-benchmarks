class Llmbench < Formula
  include Language::Python::Virtualenv

  desc "Repeatable local LLM runtime benchmark and setup checker"
  homepage "https://github.com/LucianoAdonis/local-llm-benchmarks"
  url "https://github.com/LucianoAdonis/local-llm-benchmarks/releases/download/v0.1.1/llmbench_local-0.1.1-py3-none-any.whl"
  sha256 "b52e51dcead035bb7447fb70d4523a8a63dfc52eec94be1de05dcd241a935494"
  license "MIT"
  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, "python3.12")
    system venv/"bin/python3", "-m", "pip", "install", "--no-deps", cached_download
    bin.install_symlink libexec/"bin/llmbench"
  end

  test do
    assert_match "llmbench 0.1.1", shell_output("#{bin}/llmbench --version")
  end
end
