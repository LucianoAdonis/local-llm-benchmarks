class Llmbench < Formula
  include Language::Python::Virtualenv

  desc "Repeatable local LLM runtime benchmark and setup checker"
  homepage "https://github.com/LucianoAdonis/local-llm-benchmarks"
  url "https://github.com/LucianoAdonis/local-llm-benchmarks/releases/download/v0.2.0/llmbench_local-0.2.0-py3-none-any.whl"
  sha256 "c9444d0859a0e4dbadac19437a9cc6ab73e3809f6e94fb057098327393b2fed9"
  license "MIT"
  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, "python3.12")
    system venv/"bin/python3", "-m", "pip", "install", "--no-deps", cached_download
    bin.install_symlink libexec/"bin/llmbench"
  end

  test do
    assert_match "llmbench 0.2.0", shell_output("#{bin}/llmbench --version")
  end
end
