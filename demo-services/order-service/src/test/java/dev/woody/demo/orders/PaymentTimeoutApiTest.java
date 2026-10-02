package dev.woody.demo.orders;

import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "demo.payment-mode=payment-timeout",
        "logging.file.name=target/test-logs/timeout.jsonl"
})
@AutoConfigureMockMvc
class PaymentTimeoutApiTest {

    @Autowired
    private MockMvc mvc;

    @Test
    void returnsGatewayTimeout() throws Exception {
        mvc.perform(post("/api/v1/orders")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"productId":"book-1","quantity":2}
                                """))
                .andExpect(status().isGatewayTimeout())
                .andExpect(jsonPath("$.code").value("PAYMENT_TIMEOUT"))
                .andExpect(jsonPath("$.orderId").isNotEmpty());
    }
}