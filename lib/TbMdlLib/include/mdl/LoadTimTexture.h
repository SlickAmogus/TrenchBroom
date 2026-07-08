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

#pragma once

#include "Result.h"

namespace tb::fs
{
class Reader;
}

namespace tb::gl
{
class Texture;
}

namespace tb::mdl
{

/**
 * Loads a PlayStation TIM image (PSX standard texture format, used by Silent
 * Hill among others). Supports 4bpp/8bpp CLUT and 16bpp direct-color images.
 * Multi-row CLUTs (palette variants) decode with row 0; texel value 0x0000 is
 * fully transparent per PSX GPU semantics.
 */
Result<gl::Texture> loadTimTexture(fs::Reader& reader);

} // namespace tb::mdl
