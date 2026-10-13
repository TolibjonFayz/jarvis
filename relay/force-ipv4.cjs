// Bu kompyuterda Node IPv6'da osilib qoladi (npm/wrangler) — DNS javobidan IPv6'ni olib tashlaymiz.
const dns = require('dns');
const originalLookup = dns.lookup;
dns.lookup = function (hostname, options, callback) {
  if (typeof options === 'function') { callback = options; options = {}; }
  if (typeof options === 'number') options = { family: options };
  const wantsAll = options && options.all === true;
  const patched = Object.assign({}, options, { all: true });
  return originalLookup.call(dns, hostname, patched, (err, addresses) => {
    if (err) return callback(err);
    const ipv4 = addresses.filter((a) => a.family === 4);
    const list = ipv4.length ? ipv4 : addresses;
    if (wantsAll) return callback(null, list);
    callback(null, list[0].address, list[0].family);
  });
};
