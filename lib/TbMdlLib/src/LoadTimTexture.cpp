/*
 Copyright (C) 2026 Silent Hill decomp contributors

 This file is part of TrenchBroom.

 TrenchBroom is free software: you can redistribute it and/or modify
 it under the terms of the GNU General Public License as published by
 the Free Software Foundation, either version 3 of the License, or
 (at your option) any later version.

 TrenchBroom is distributed in the hope that it will be useful,
 but WITHOUT ANY WARRANTY; without even the implied warranty of
 MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 GNU General Public License for more details.

 You should have received a copy of the GNU General Public License
 along with TrenchBroom. If not, see <http://www.gnu.org/licenses/>.
 */

#include "mdl/LoadTimTexture.h"

#include "Color.h"
#include "fs/Reader.h"
#include "fs/ReaderException.h"
#include "gl/Texture.h"
#include "mdl/LoadFreeImageTexture.h" // getAverageColor
#include "mdl/MaterialUtils.h"

#include <fmt/format.h>

#include <cstdint>
#include <vector>

namespace tb::mdl
{
namespace
{

constexpr uint32_t TimMagic = 0x10;

// PSX 16-bit texel: A1B5G5R5. Raw value 0 = fully transparent (GPU rule);
// the STP bit on a non-black texel selects semi-transparent blending in-game,
// which has no editor equivalent and renders opaque here.
void writeTexel(unsigned char* out, const uint16_t c16, bool& hasTransparency)
{
  if (c16 == 0)
  {
    out[0] = out[1] = out[2] = out[3] = 0;
    hasTransparency = true;
    return;
  }
  const auto r = static_cast<unsigned char>((c16 & 0x1F) << 3);
  const auto g = static_cast<unsigned char>(((c16 >> 5) & 0x1F) << 3);
  const auto b = static_cast<unsigned char>(((c16 >> 10) & 0x1F) << 3);
  out[0] = static_cast<unsigned char>(r | (r >> 5));
  out[1] = static_cast<unsigned char>(g | (g >> 5));
  out[2] = static_cast<unsigned char>(b | (b >> 5));
  out[3] = 255;
}

} // namespace

Result<gl::Texture> loadTimTexture(fs::Reader& reader)
{
  try
  {
    const auto magic = reader.readInt<uint32_t>();
    if (magic != TimMagic)
    {
      return Error{fmt::format("Unknown TIM magic: {}", magic)};
    }

    const auto flags = reader.readInt<uint32_t>();
    const auto pmode = flags & 7u;
    const auto hasClut = (flags & 8u) != 0u;

    if (pmode > 2u)
    {
      return Error{fmt::format("Unsupported TIM pixel mode: {}", pmode)};
    }
    if (pmode < 2u && !hasClut)
    {
      return Error{"CLUT TIM without CLUT block"};
    }

    // CLUT block: {u32 size; u16 x, y, w, h; u16 entries[w*h]}. Multi-row
    // CLUTs are palette variants; row 0 is the canonical preview.
    auto clut = std::vector<uint16_t>{};
    auto clutWidth = size_t(0);
    if (hasClut)
    {
      const auto blockSize = reader.readSize<uint32_t>();
      reader.seekForward(4); // clut x, y
      clutWidth = reader.readSize<uint16_t>();
      const auto clutHeight = reader.readSize<uint16_t>();
      const auto entryCount = clutWidth * clutHeight;
      if (blockSize < 12 + entryCount * 2 || !reader.canRead(blockSize - 12))
      {
        return Error{"Corrupt TIM CLUT block"};
      }
      clut.resize(entryCount);
      for (auto& entry : clut)
      {
        entry = reader.readInt<uint16_t>();
      }
    }

    // Pixel block: {u32 size; u16 x, y; u16 storedWidth (halfwords), height}.
    reader.seekForward(4); // pixel block size
    reader.seekForward(4); // pixel x, y
    const auto storedWidth = reader.readSize<uint16_t>();
    const auto height = reader.readSize<uint16_t>();
    const auto width = storedWidth * (pmode == 0u ? 4u : pmode == 1u ? 2u : 1u);

    if (!checkTextureDimensions(width, height))
    {
      return Error{fmt::format("Invalid texture dimensions: {}*{}", width, height)};
    }
    if (!reader.canRead(storedWidth * height * 2))
    {
      return Error{"Corrupt TIM pixel block"};
    }

    constexpr auto mipCount = 1u;
    auto buffers = gl::TextureBufferList{mipCount};
    setMipBufferSize(buffers, mipCount, width, height, GL_RGBA);
    auto* out = buffers.at(0).data();

    auto hasTransparency = false;
    const auto clutTexel = [&](const size_t idx) {
      return idx < clut.size() ? clut[idx] : uint16_t(0);
    };

    for (size_t y = 0; y < height; ++y)
    {
      for (size_t xw = 0; xw < storedWidth; ++xw)
      {
        const auto halfword = reader.readInt<uint16_t>();
        auto* row = out + (y * width) * 4;
        switch (pmode)
        {
        case 0: // 4bpp: 4 texels per halfword, low nibble = leftmost
          for (size_t k = 0; k < 4; ++k)
          {
            writeTexel(
              row + (xw * 4 + k) * 4,
              clutTexel((halfword >> (k * 4)) & 0xF),
              hasTransparency);
          }
          break;
        case 1: // 8bpp: 2 texels per halfword, low byte = leftmost
          writeTexel(row + (xw * 2) * 4, clutTexel(halfword & 0xFF), hasTransparency);
          writeTexel(
            row + (xw * 2 + 1) * 4, clutTexel((halfword >> 8) & 0xFF), hasTransparency);
          break;
        default: // 16bpp direct color
          writeTexel(row + xw * 4, halfword, hasTransparency);
          break;
        }
      }
    }

    const auto averageColor = getAverageColor(buffers.at(0), GL_RGBA);
    return gl::Texture{
      width,
      height,
      averageColor,
      GL_RGBA,
      hasTransparency ? gl::TextureMask::On : gl::TextureMask::Off,
      gl::NoEmbeddedDefaults{},
      std::move(buffers)};
  }
  catch (const fs::ReaderException& e)
  {
    return Error{e.what()};
  }
}

} // namespace tb::mdl
