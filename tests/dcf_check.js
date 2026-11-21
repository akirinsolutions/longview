const assert = require("assert");
const DCF = require("../app/static/dcf.js");

/* Apple, the reference set used on the Company page. */
const aapl = {
  fcf: 105658376192,
  shares: 14532182000,
  cash: 56722001920,
  debt: 94478999552,
  price: 342.37,
};

const at = (growth, discount, years) =>
  DCF.valuePerShare({ ...aapl, growth, discount, years });

const base = at(6, 5.5, 11);
assert(base > 341 && base < 342, "six percent / 5.5% should be about $341");

const higherGrowth = at(8, 5.5, 11);
assert(higherGrowth > base, "higher growth must raise the value");

const higherDiscount = at(6, 8, 11);
assert(higherDiscount < base, "higher discount must lower the value");

assert.strictEqual(at(6, 2.5, 11), null, "discount must beat 2.5%");

const implied = DCF.impliedGrowth({ ...aapl, discount: 5.5, years: 11 });
assert(Math.abs(implied.growth - 6.03) < 0.15,
  "Apple at 5.5% should imply about 6% growth");

const roundTrip = DCF.valuePerShare({
  ...aapl, growth: implied.growth, discount: 5.5, years: 11,
});
assert(Math.abs(roundTrip - aapl.price) < 0.01,
  "the implied growth must reproduce the price");

const shorter = DCF.impliedGrowth({ ...aapl, discount: 5.5, years: 5 });
assert(shorter.growth > implied.growth,
  "a shorter high-growth window needs faster growth");

assert.strictEqual(DCF.impliedGrowth({ ...aapl, discount: 2.5, years: 11 }), null);

console.log("dcf ok");
